"""步骤 7：提示词切换测试（晴 -> 雨 -> 晴 -> 黄昏），对比 transition.num_steps。
用法（头节点，Scope 的 venv）：
    ~/scope/.venv/bin/python test_transition.py http://TC2N01:8000
结果写到 ~/results/transition/：frame_<场景>_<序号>_<秒>.jpg 与 events.jsonl。
"""
import json
import os
import sys
import time
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
OUT = os.path.expanduser("~/results/transition")
os.makedirs(OUT, exist_ok=True)

STYLE = "mountain lake with snow-capped peaks, cinematic landscape, photorealistic"
SCENES = {
    "sunny": f"A {STYLE}, clear blue sky, bright midday sunlight, calm water",
    "rain": f"A {STYLE}, heavy rain falling, dark grey storm clouds, wet misty air, rain ripples on water",
    "dusk": f"A {STYLE}, golden sunset dusk, orange and pink sky, warm light reflecting on water",
}
# (目标场景, num_steps, 抓帧数, 抓帧间隔秒)
PLAN = [("rain", 4, 12, 3), ("sunny", 20, 12, 3), ("dusk", 0, 12, 3)]


def call(method, path, body=None, raw=False):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        BASE + path, data=data, method=method, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        payload = r.read()
    return payload if raw else json.loads(payload or b"{}")


events = open(os.path.join(OUT, "events.jsonl"), "w")


def log(**kw):
    kw["wall"] = round(time.time() - T0, 1)
    events.write(json.dumps(kw) + "\n")
    events.flush()
    print(kw, flush=True)


def grab(tag, i):
    jpg = call("GET", "/api/v1/session/frame", raw=True)
    with open(os.path.join(OUT, f"frame_{tag}_{i:02d}_{int(time.time() - T0)}s.jpg"), "wb") as f:
        f.write(jpg)


T0 = time.time()
call(
    "POST",
    "/api/v1/session/start",
    {"pipeline_id": "longlive", "input_mode": "text", "prompts": [{"text": SCENES["sunny"], "weight": 1.0}]},
)
log(event="start", scene="sunny")
time.sleep(35)  # 预热到稳定
grab("sunny0", 0)

for scene, steps, n, gap in PLAN:
    r = call(
        "POST",
        "/api/v1/session/parameters",
        {"transition": {"target_prompts": [{"text": SCENES[scene], "weight": 1.0}], "num_steps": steps}},
    )
    log(event="transition", to=scene, num_steps=steps, resp=str(r)[:120])
    for i in range(1, n + 1):
        time.sleep(gap)
        grab(f"{scene}_n{steps}", i)
    m = call("GET", "/api/v1/session/metrics")
    log(event="metrics", scene=scene, pipeline_fps=m["sessions"].get("headless", {}).get("pipeline_fps"))

print("stop:", call("POST", "/api/v1/session/stop"), flush=True)
