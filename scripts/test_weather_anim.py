"""强提示词天气/时间切换 + 录像 + 延迟测量（底图：循环 mp4，噪声 1.0，num_steps=0）。
用法（头节点，Scope 的 venv，需要 PIL/numpy）：
    ~/scope/.venv/bin/python test_weather_anim.py http://TC2N01:8000 /home/msai/<user>/assets/moraine_576x320.mp4 [标签]
流程：晴 → 暴雨 → 日落 → 夜晚 → 晴。每个阶段 45 秒，约每 0.5 秒抓一帧并记录时间。
输出 ~/results/anim_<标签>/：frames/、stream.ts（若能录到）、events.json、metrics.csv、latency.json
"""
import csv
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request

import numpy as np
from PIL import Image

BASE, VIDEO = sys.argv[1], sys.argv[2]
TAG = sys.argv[3] if len(sys.argv) > 3 else "v1"
OUT = os.path.expanduser(f"~/results/anim_{TAG}")
FR = os.path.join(OUT, "frames")
os.makedirs(FR, exist_ok=True)

BASE_SCENE = (
    "A mountain lake in the Canadian Rockies, rugged snow-capped peaks, dense evergreen forest, "
    "turquoise water with a mirror reflection, cinematic landscape, photorealistic"
)
SCENES = {
    "sunny": BASE_SCENE + ", clear blue sky, bright midday sunlight",
    "storm": BASE_SCENE
    + ", violent thunderstorm, torrential heavy rain pouring down with thick rain streaks across the whole scene, "
    "very dark heavy black storm clouds covering the entire sky, dim gloomy overcast light, mountains shrouded in "
    "mist and low clouds, wet dark forest, rain splashing and rippling on the lake, desaturated cold grey-blue tones, no sun",
    "sunset": BASE_SCENE
    + ", sunset, the sky blazing orange pink and purple, warm golden light glowing on the snow peaks, long dark "
    "shadows, the lake reflecting fiery orange sky, low sun",
    "night": BASE_SCENE
    + ", deep night, dark navy sky full of bright stars and a bright full moon, moonlit snow peaks glowing pale blue, "
    "very dark forest, the lake reflecting stars and moonlight",
}
PLAN = [("storm", 45), ("sunset", 45), ("night", 45), ("sunny", 45)]
WARMUP = 25


def call(method, path, body=None, raw=False, timeout=60):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        BASE + path, data=data, method=method, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        payload = r.read()
    return payload if raw else json.loads(payload or b"{}")


events = []
T0 = None


def now():
    return time.time() - T0


# 1) 开始会话（噪声 1.0）
call(
    "POST",
    "/api/v1/session/start",
    {
        "pipeline_id": "longlive",
        "input_mode": "video",
        "prompts": [{"text": SCENES["sunny"], "weight": 1.0}],
        "input_source": {"enabled": True, "source_type": "video_file", "source_name": VIDEO},
        "parameters": {"noise_scale": 1.0},
    },
)
T0 = time.time()
events.append({"t": 0.0, "event": "start", "scene": "sunny"})

# 2) 尝试同时录视频流（失败也不影响抓帧）
total = WARMUP + sum(d for _, d in PLAN) + 10
ts_path = os.path.join(OUT, "stream.ts")
ts_proc = subprocess.Popen(
    ["curl", "-s", "-m", str(total), "-o", ts_path, BASE + "/api/v1/session/output.ts"],
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)

# 3) 抓帧线程
stop = threading.Event()
frames = []  # (t, path)


def grabber():
    i = 0
    while not stop.is_set():
        t_req = now()
        try:
            jpg = call("GET", "/api/v1/session/frame", raw=True, timeout=20)
            t = now()
            p = os.path.join(FR, f"f_{i:05d}.jpg")
            with open(p, "wb") as f:
                f.write(jpg)
            frames.append((t, p))
            i += 1
        except Exception as e:
            events.append({"t": round(t_req, 2), "event": "frame_error", "err": str(e)[:100]})
            time.sleep(0.5)
        time.sleep(0.2)


th = threading.Thread(target=grabber, daemon=True)
th.start()

time.sleep(WARMUP)
for scene, dur in PLAN:
    t_cmd = now()
    call(
        "POST",
        "/api/v1/session/parameters",
        {"transition": {"target_prompts": [{"text": SCENES[scene], "weight": 1.0}], "num_steps": 0}},
    )
    events.append({"t": round(t_cmd, 2), "event": "command", "scene": scene, "num_steps": 0, "ack": round(now(), 2)})
    print(events[-1], flush=True)
    time.sleep(dur)

stop.set()
th.join(timeout=10)
call("POST", "/api/v1/session/stop")
try:
    ts_proc.wait(timeout=15)
except Exception:
    ts_proc.kill()

json.dump(events, open(os.path.join(OUT, "events.json"), "w"), indent=1)

# 4) 指标：整帧亮度、天空带(上 25%)亮度、平均 R/G/B、饱和度
rows = []
for t, p in frames:
    a = np.asarray(Image.open(p).convert("RGB"), dtype=np.float32)
    lum = a.mean(axis=2)
    h = a.shape[0]
    mx, mn = a.max(axis=2), a.min(axis=2)
    sat = ((mx - mn) / (mx + 1e-3)).mean()
    rows.append(
        {
            "t": round(t, 2),
            "lum": round(float(lum.mean()), 2),
            "sky_lum": round(float(lum[: h // 4].mean()), 2),
            "lake_lum": round(float(lum[int(h * 0.75):].mean()), 2),
            "r": round(float(a[..., 0].mean()), 2),
            "g": round(float(a[..., 1].mean()), 2),
            "b": round(float(a[..., 2].mean()), 2),
            "sat": round(float(sat), 3),
        }
    )
with open(os.path.join(OUT, "metrics.csv"), "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)

# 5) 延迟：对每个指令，用整帧(lum,r,g,b)变化向量，找开始变化与完成 90% 的时间
cmds = [e for e in events if e["event"] == "command"]
vec = lambda r: np.array([r["lum"], r["r"], r["g"], r["b"]])
lat = []
for i, c in enumerate(cmds):
    t0 = c["t"]
    t1 = cmds[i + 1]["t"] if i + 1 < len(cmds) else rows[-1]["t"]
    before = [r for r in rows if t0 - 5 <= r["t"] < t0]
    after = [r for r in rows if t0 <= r["t"] < t1]
    end = [r for r in after if r["t"] >= t1 - 8]
    if not before or len(after) < 5 or not end:
        lat.append({"scene": c["scene"], "error": "not enough frames"})
        continue
    v0 = np.mean([vec(r) for r in before], axis=0)
    v1 = np.mean([vec(r) for r in end], axis=0)
    total_change = np.linalg.norm(v1 - v0)
    res = {"scene": c["scene"], "total_change": round(float(total_change), 1)}
    for name, frac in (("t_first_visible_s", 0.10), ("t_50pct_s", 0.5), ("t_90pct_s", 0.9)):
        res[name] = None
        for r in after:
            prog = np.dot(vec(r) - v0, v1 - v0) / (total_change**2 + 1e-6)
            if prog >= frac:
                res[name] = round(r["t"] - t0, 1)
                break
    lat.append(res)
json.dump(lat, open(os.path.join(OUT, "latency.json"), "w"), indent=1, ensure_ascii=False)
print(json.dumps(lat, ensure_ascii=False), flush=True)
print("frames:", len(frames), "span:", round(frames[-1][0] - frames[0][0], 1), "s", flush=True)
