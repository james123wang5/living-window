"""实时壁纸原型的本地桥接服务（在 Mac 上运行，只用 Python 标准库 + ffmpeg）。

浏览器 ⇄ 本服务 (http://127.0.0.1:8765) ⇄ SSH 隧道 ⇄ 集群计算节点上的 Scope (:8000)

  GET  /             页面
  GET  /stream       连续推送帧：每帧 [4 字节长度][8 字节服务端收到时间(秒)][JPEG]
  POST /api/command  {"text": "..."} → 提示词层 → 发给 Scope（解除暂停 + 渐变）；过渡完成后自动暂停，定住最后一帧
  POST /api/reset    重开会话（回到原图）
  GET  /api/state    场景状态、生成/定住、帧率

方案：深度图（锁结构）+ 原图做参考图（保身份）+ 提示词渐变（丝滑），见 技术选型-虚拟窗景.md §0.15。
用法：先建隧道（见 README），再 python3 server.py
"""
import json
import os
import queue
import struct
import subprocess
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import prompt_layer

SCOPE = os.environ.get("SCOPE_URL", "http://127.0.0.1:18000")
PORT = int(os.environ.get("APP_PORT", "8765"))
HERE = os.path.dirname(os.path.abspath(__file__))
REMOTE_ASSETS = "/home/msai/<user>/assets"
DEPTH = f"{REMOTE_ASSETS}/moraine_576x320_depth.mp4"
REF = f"{REMOTE_ASSETS}/moraine_576x320.png"
FRAMES_PER_CHUNK = 12  # LongLive 每块约 12 帧
SETTLE_CHUNKS = 4  # 过渡完成后再多生成几块再定住


def scope(method, path, body=None, timeout=120):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(SCOPE + path, data=data, method=method, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or b"{}")


def session_body(prompt):
    return {
        "input_mode": "video",
        "prompts": [{"text": prompt, "weight": 1.0}],
        "parameters": {"vace_ref_images": [REF], "vace_context_scale": 1.0},
        "graph": {
            "nodes": [
                {"id": "depth", "type": "source", "source_mode": "video_file", "source_name": DEPTH},
                {"id": "longlive", "type": "pipeline", "pipeline_id": "longlive"},
                {"id": "output", "type": "sink"},
            ],
            "edges": [
                {"from": "depth", "from_port": "video", "to_node": "longlive", "to_port": "vace_input_frames", "kind": "stream"},
                {"from": "longlive", "from_port": "video", "to_node": "output", "to_port": "video", "kind": "stream"},
            ],
        },
    }


class FrameHub:
    """用 ffmpeg 把 Scope 的 MPEG-TS 流解成 JPEG，分发给所有浏览器连接。"""

    def __init__(self):
        self.subs = set()
        self.lock = threading.Lock()
        self.last = None
        self.count = 0
        self.times = []
        self.proc = None
        self.connected_at = 0.0
        self.last_frame_at = 0.0

    def restart(self):
        """断开当前 ffmpeg，让 run() 重连（会话重开后旧连接不会再有数据）。"""
        p = self.proc
        if p and p.poll() is None:
            p.kill()

    def subscribe(self):
        q = queue.Queue(maxsize=240)
        with self.lock:
            self.subs.add(q)
            if self.last:
                q.put(self.last)
        return q

    def unsubscribe(self, q):
        with self.lock:
            self.subs.discard(q)

    def fps(self):
        now = time.time()
        recent = [t for t in self.times if now - t < 15]
        if len(recent) < 2:
            return 0.0
        return round((len(recent) - 1) / (recent[-1] - recent[0] + 1e-6), 2)

    def publish(self, jpeg):
        t = time.time()
        pkt = struct.pack(">Id", len(jpeg), t) + jpeg
        with self.lock:
            self.last = pkt
            self.count += 1
            self.last_frame_at = t
            self.times = [x for x in self.times if t - x < 30] + [t]
            for q in list(self.subs):
                if q.full():
                    try:
                        q.get_nowait()
                    except queue.Empty:
                        pass
                q.put_nowait(pkt)

    def run(self):
        while True:
            # 流的时间戳按 30 FPS 标，实际只有约 4–5 FPS；默认探测约 5 秒流内时间要等 30 多秒，所以把探测压到最小
            cmd = ["ffmpeg", "-loglevel", "error", "-probesize", "32768", "-analyzeduration", "0",
                   "-i", SCOPE + "/api/v1/session/output.ts",
                   # 新版 ffmpeg 的 mjpeg 编码器要求全范围像素格式，否则直接拒绝编码
                   "-f", "image2pipe", "-c:v", "mjpeg", "-pix_fmt", "yuvj420p", "-q:v", "2", "pipe:1"]
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            self.proc, self.connected_at = p, time.time()
            buf = b""
            while True:
                chunk = p.stdout.read1(1 << 16) if hasattr(p.stdout, "read1") else p.stdout.read(1 << 16)
                if not chunk:
                    break
                buf += chunk
                while True:
                    s = buf.find(b"\xff\xd8")
                    e = buf.find(b"\xff\xd9", s + 2) if s >= 0 else -1
                    if s < 0 or e < 0:
                        break
                    self.publish(buf[s:e + 2])
                    buf = buf[e + 2:]
            p.wait()
            time.sleep(1)  # 会话重开或断流后重连


HUB = FrameHub()
STATE = {"scene": dict(prompt_layer.INITIAL_STATE), "status": "starting", "history": [], "cmd_id": 0}
STATE_LOCK = threading.Lock()


def hold_after(cmd_id, frames_needed):
    """等生成够这么多帧后暂停（定住最后一帧）；期间若有新指令则放弃。"""
    start = HUB.count
    deadline = time.time() + 120
    while time.time() < deadline:
        if STATE["cmd_id"] != cmd_id:
            return
        if HUB.count - start >= frames_needed:
            break
        time.sleep(0.2)
    if STATE["cmd_id"] != cmd_id:
        return
    if HUB.count - start < frames_needed:
        # 没收够帧就不定住（多半是视频流没接上），保持生成，让看门狗重连
        STATE["status"] = "generating"
        return
    try:
        scope("POST", "/api/v1/session/parameters", {"paused": True})
        STATE["status"] = "holding"
    except Exception as e:
        STATE["status"] = f"pause failed: {e}"


def start_session():
    STATE["status"] = "starting"
    try:
        scope("POST", "/api/v1/session/stop")
    except Exception:
        pass
    with STATE_LOCK:
        STATE["scene"] = dict(prompt_layer.INITIAL_STATE)
        STATE["cmd_id"] += 1
        cid = STATE["cmd_id"]
    scope("POST", "/api/v1/session/start", session_body(prompt_layer.initial_prompt()), timeout=300)
    HUB.restart()
    STATE["status"] = "generating"
    threading.Thread(target=hold_after, args=(cid, FRAMES_PER_CHUNK * 4), daemon=True).start()


def command(text):
    with STATE_LOCK:
        scene, prompt, params, notes = prompt_layer.plan(text, STATE["scene"])
        STATE["scene"] = scene
        STATE["cmd_id"] += 1
        cid = STATE["cmd_id"]
    t_sent = time.time()
    scope("POST", "/api/v1/session/parameters", {"paused": False, **params})
    STATE["status"] = "generating"
    steps = params["transition"]["num_steps"]
    threading.Thread(target=hold_after, args=(cid, FRAMES_PER_CHUNK * (steps + SETTLE_CHUNKS)), daemon=True).start()
    item = {"text": text, "prompt": prompt, "notes": notes, "t_sent": t_sent, "frame_at_send": HUB.count}
    STATE["history"].append(item)
    return item


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        data = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            data = open(os.path.join(HERE, "index.html"), "rb").read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif self.path == "/stream":
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            q = HUB.subscribe()
            try:
                while True:
                    try:
                        pkt = q.get(timeout=15)
                    except queue.Empty:
                        continue
                    self.wfile.write(pkt)
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                HUB.unsubscribe(q)
        elif self.path == "/api/state":
            self._json({"status": STATE["status"], "scene": STATE["scene"], "fps": HUB.fps(), "frames": HUB.count,
                        "server_time": time.time()})
        else:
            self.send_error(404)

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        try:
            if self.path == "/api/command":
                self._json(command(body.get("text", "")))
            elif self.path == "/api/reset":
                threading.Thread(target=start_session, daemon=True).start()
                self._json({"ok": True})
            else:
                self.send_error(404)
        except Exception as e:
            self._json({"error": str(e)}, 500)


def watchdog():
    """生成中却长时间收不到帧 → 重连视频流（定住时没帧是正常的）。"""
    while True:
        time.sleep(2)
        now = time.time()
        if STATE["status"] == "generating" and now - HUB.connected_at > 8 and now - HUB.last_frame_at > 8:
            HUB.restart()


if __name__ == "__main__":
    threading.Thread(target=HUB.run, daemon=True).start()
    threading.Thread(target=watchdog, daemon=True).start()
    threading.Thread(target=start_session, daemon=True).start()
    print(f"open http://127.0.0.1:{PORT}  (Scope: {SCOPE})", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
