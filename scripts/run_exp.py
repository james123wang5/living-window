"""通用实验脚本：开会话 → 按时间表发参数 → 录完整视频流（带每帧到达时间）→ 分析延迟与平滑度。
用法（头节点，Scope 的 venv，需要 av/numpy）：
    ~/scope/.venv/bin/python run_exp.py http://TC2N01:8000 exp.json
exp.json 字段：
    tag            输出目录名，结果写到 ~/results/<tag>/
    session        POST /api/v1/session/start 的请求体（可含 graph）
    warmup         开始后等多少秒再执行第一条指令
    schedule       [{"label": "...", "params": {...}, "hold": 秒}]，依次 POST /api/v1/session/parameters
输出：stream.ts、frames.csv（每帧到达时间与区域差）、events.json、summary.json
"""
import bisect
import csv
import json
import os
import sys
import threading
import time
import urllib.request

import av
import numpy as np

BASE, CFG = sys.argv[1], json.load(open(sys.argv[2]))
OUT = os.path.expanduser(f"~/results/{CFG['tag']}")
os.makedirs(OUT, exist_ok=True)


def call(method, path, body=None, timeout=300):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        BASE + path, data=data, method=method, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or b"{}")


events = []
T0 = time.time()


def now():
    return time.time() - T0


def log(**kw):
    kw["t"] = round(now(), 3)
    events.append(kw)
    print(kw, flush=True)


# 1) 开会话（图模式下首次会加载深度等节点，可能较慢）
r = call("POST", "/api/v1/session/start", CFG["session"])
log(event="start", resp=str(r)[:200])

# 2) 录流：边读边记“到达时间 ↔ 累计字节数”，之后用每帧的字节位置换算到达时间
stop = threading.Event()
byte_log = []  # (t, total_bytes_after_chunk)


def recorder():
    total = 0
    try:
        with urllib.request.urlopen(BASE + "/api/v1/session/output.ts", timeout=30) as resp, open(
            os.path.join(OUT, "stream.ts"), "wb"
        ) as f:
            while not stop.is_set():
                chunk = resp.read1(65536) if hasattr(resp, "read1") else resp.read(65536)
                if not chunk:
                    break
                f.write(chunk)
                total += len(chunk)
                byte_log.append((now(), total))
    except Exception as e:
        log(event="recorder_error", err=str(e)[:200])


rec = threading.Thread(target=recorder, daemon=True)
rec.start()

# 2b) 延迟探针：视频流经 libx264 默认参数编码，会先缓冲约 40 帧，用它测延迟会偏大；
#     这里每 0.25 秒取一次最新帧（不经编码器），只用于测延迟，粒度约为一块（约 12 帧）
probe = []  # (t, 区域颜色向量)


def prober():
    import io

    from PIL import Image

    while not stop.is_set():
        try:
            req = urllib.request.Request(BASE + "/api/v1/session/frame")
            with urllib.request.urlopen(req, timeout=10) as r:
                im = np.asarray(Image.open(io.BytesIO(r.read())).convert("RGB"))[::4, ::4].astype(np.float32)
            hh = im.shape[0]
            v = np.concatenate([im[s].reshape(-1, 3).mean(0) for s in (slice(0, hh // 4), slice(hh // 4, hh // 2), slice(hh // 2, int(hh * 0.75)), slice(int(hh * 0.75), hh))])
            probe.append((now(), v))
        except Exception:
            pass
        time.sleep(0.25)


pb = threading.Thread(target=prober, daemon=True)
pb.start()

time.sleep(CFG.get("warmup", 20))
for step in CFG["schedule"]:
    call("POST", "/api/v1/session/parameters", step["params"])
    log(event="command", label=step["label"])
    time.sleep(step["hold"])

stop.set()
try:
    call("POST", "/api/v1/session/stop")
except Exception as e:
    log(event="stop_error", err=str(e)[:200])
rec.join(timeout=20)
json.dump(events, open(os.path.join(OUT, "events.json"), "w"), indent=1, ensure_ascii=False)

# 3) 解码：每帧 → 到达时间（按包的字节位置），并缩小后算区域差
bt = [b for _, b in byte_log]


def arrival(pos):
    if pos is None or pos < 0 or not bt:
        return None
    i = bisect.bisect_left(bt, pos)
    return byte_log[min(i, len(byte_log) - 1)][0]


frames = []  # (t_arrival, small_gray, small_rgb)
c = av.open(os.path.join(OUT, "stream.ts"))
for pkt in c.demux(video=0):
    for fr in pkt.decode():
        rgb = fr.to_ndarray(format="rgb24")[::4, ::4].astype(np.float32)
        frames.append((arrival(pkt.pos), rgb))
c.close()
frames = [f for f in frames if f[0] is not None]
h = frames[0][1].shape[0]
REG = {"sky": slice(0, h // 4), "upper": slice(h // 4, h // 2), "mid": slice(h // 2, int(h * 0.75)), "lake": slice(int(h * 0.75), h)}

rows = []
for k, (t, a) in enumerate(frames):
    row = {"i": k, "t": round(t, 3)}
    g = a.mean(axis=2)
    if k:
        pg = frames[k - 1][1].mean(axis=2)
        row["d"] = round(float(np.abs(g - pg).mean()), 3)
        for n, s in REG.items():
            row[f"d_{n}"] = round(float(np.abs(g[s] - pg[s]).mean()), 3)
    for n, s in REG.items():
        m = a[s].reshape(-1, 3).mean(axis=0)
        row[f"{n}_r"], row[f"{n}_g"], row[f"{n}_b"] = (round(float(x), 2) for x in m)
    rows.append(row)
keys = sorted({k for r in rows for k in r}, key=lambda x: (x not in ("i", "t"), x))
with open(os.path.join(OUT, "frames.csv"), "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=keys)
    w.writeheader()
    w.writerows(rows)

# 4) 汇总：帧率、平滑度、每条指令的延迟（整帧颜色向量的推进比例）
ts = np.array([r["t"] for r in rows])
d = np.array([r.get("d", 0) for r in rows[1:]])
med = float(np.median(d))
span = ts[-1] - ts[0]
summary = {"frames": len(rows), "span_s": round(float(span), 1), "fps": round(len(rows) / span, 2),
           "d_median": round(med, 2), "d_p95": round(float(np.percentile(d, 95)), 2),
           "big_jumps": int((d > 3 * med + 1).sum()), "commands": []}
vec = np.array([[r[f"{n}_{ch}"] for n in REG for ch in "rgb"] for r in rows])
cmds = [e for e in events if e["event"] == "command"]
for j, e in enumerate(cmds):
    t0 = e["t"]
    t1 = cmds[j + 1]["t"] if j + 1 < len(cmds) else ts[-1]
    pre = vec[(ts >= t0 - 3) & (ts < t0)]
    post = vec[(ts >= t1 - 5) & (ts < t1)]
    win = (ts >= t0) & (ts < t1)
    res = {"label": e["label"]}
    if len(pre) and len(post) and win.sum() > 5:
        v0, v1 = pre.mean(0), post.mean(0)
        tot = float(np.linalg.norm(v1 - v0))
        res["total_change"] = round(tot, 1)
        prog = (vec[win] - v0) @ (v1 - v0) / (tot**2 + 1e-6)
        tw = ts[win] - t0
        for name, q in (("t10", 0.1), ("t50", 0.5), ("t90", 0.9)):
            hit = np.where(prog >= q)[0]
            res[name] = round(float(tw[hit[0]]), 2) if len(hit) else None
        dw = d[np.where(win[1:])[0]]
        res["max_jump"] = round(float(dw.max()), 1) if len(dw) else None
        # 有多少帧承担了变化：变化窗口内（10%→90%）有几帧
        if res["t10"] is not None and res["t90"] is not None:
            res["frames_10_to_90"] = int(((tw >= res["t10"]) & (tw <= res["t90"])).sum())
    # 探针测的延迟（不含编码器缓冲）
    pt = np.array([p[0] for p in probe])
    pv = np.array([p[1] for p in probe]) if probe else np.zeros((0, 12))
    ppre, ppost, pwin = pv[(pt >= t0 - 3) & (pt < t0)], pv[(pt >= t1 - 5) & (pt < t1)], (pt >= t0) & (pt < t1)
    if len(ppre) and len(ppost) and pwin.sum() > 3:
        v0, v1 = ppre.mean(0), ppost.mean(0)
        tot = float(np.linalg.norm(v1 - v0))
        prog = (pv[pwin] - v0) @ (v1 - v0) / (tot**2 + 1e-6)
        tw = pt[pwin] - t0
        for name, q in (("probe_t10", 0.1), ("probe_t50", 0.5), ("probe_t90", 0.9)):
            hit = np.where(prog >= q)[0]
            res[name] = round(float(tw[hit[0]]), 2) if len(hit) else None
    summary["commands"].append(res)
json.dump([(round(t, 3), v.round(2).tolist()) for t, v in probe], open(os.path.join(OUT, "probe.json"), "w"))
json.dump(summary, open(os.path.join(OUT, "summary.json"), "w"), indent=1, ensure_ascii=False)
print(json.dumps(summary, ensure_ascii=False), flush=True)
