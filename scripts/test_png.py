"""步骤 6：把静态 PNG（循环 mp4）作为 LongLive 的视频输入，看能否保持原图并随提示词变化。
用法（头节点，Scope 的 venv）：
    ~/scope/.venv/bin/python test_png.py http://TC2N01:8000 /home/msai/<user>/assets/moraine_576x320.mp4 [标签]
阶段：A 默认噪声 → B 降噪声 → C 切到雨天（transition 4 步）。每 5 秒抓一帧。
结果：~/results/png_<标签>/
"""
import json
import os
import sys
import time
import urllib.request

BASE, VIDEO = sys.argv[1], sys.argv[2]
TAG = sys.argv[3] if len(sys.argv) > 3 else "run"
OUT = os.path.expanduser(f"~/results/png_{TAG}")
os.makedirs(OUT, exist_ok=True)

BASE_SCENE = (
    "A mountain lake in the Canadian Rockies, rugged snow-capped peaks, dense evergreen forest, "
    "turquoise water with a mirror reflection, cinematic landscape, photorealistic"
)
SUNNY = BASE_SCENE + ", clear blue sky, bright sunlight"
RAIN = BASE_SCENE + ", heavy rain falling, dark grey storm clouds, wet misty air"


def call(method, path, body=None, raw=False):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        BASE + path, data=data, method=method, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        payload = r.read()
    return payload if raw else json.loads(payload or b"{}")


T0 = time.time()
events = open(os.path.join(OUT, "events.jsonl"), "w")


def log(**kw):
    kw["t"] = round(time.time() - T0, 1)
    events.write(json.dumps(kw) + "\n")
    events.flush()
    print(kw, flush=True)


def grab(tag, n, gap):
    for i in range(1, n + 1):
        time.sleep(gap)
        try:
            jpg = call("GET", "/api/v1/session/frame", raw=True)
            with open(os.path.join(OUT, f"{tag}_{i:02d}_{int(time.time() - T0)}s.jpg"), "wb") as f:
                f.write(jpg)
        except Exception as e:
            log(event="frame_error", err=str(e)[:150])
    m = call("GET", "/api/v1/session/metrics")["sessions"].get("headless", {})
    log(event="metrics", phase=tag, pipeline_fps=m.get("pipeline_fps"), frames_in=m.get("frames_in"), frames_out=m.get("frames_out"))


r = call(
    "POST",
    "/api/v1/session/start",
    {
        "pipeline_id": "longlive",
        "input_mode": "video",
        "prompts": [{"text": SUNNY, "weight": 1.0}],
        "input_source": {"enabled": True, "source_type": "video_file", "source_name": VIDEO},
    },
)
log(event="start", resp=str(r)[:200])

grab("A_default", 8, 5)
call("POST", "/api/v1/session/parameters", {"noise_scale": 0.4})
log(event="noise_scale", value=0.4)
grab("B_noise04", 8, 5)
call(
    "POST",
    "/api/v1/session/parameters",
    {"transition": {"target_prompts": [{"text": RAIN, "weight": 1.0}], "num_steps": 4}},
)
log(event="transition", to="rain", num_steps=4)
grab("C_rain", 10, 5)
print("stop:", call("POST", "/api/v1/session/stop"), flush=True)
