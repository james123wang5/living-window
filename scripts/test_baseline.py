"""步骤 6 基线：用文本提示词让 LongLive 生成山水场景，记录帧率/显存并抓帧。
在集群头节点用 Scope 的 venv 运行（只用标准库，不需要 GPU）：
    ~/scope/.venv/bin/python test_baseline.py http://TC2N01:8000 [秒数]
结果写到 ~/results/baseline/（metrics.jsonl 和若干 frame_*.jpg）。
"""
import json
import os
import sys
import time
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
DURATION = int(sys.argv[2]) if len(sys.argv) > 2 else 60
OUT = os.path.expanduser("~/results/baseline")
os.makedirs(OUT, exist_ok=True)

PROMPT = (
    "A serene mountain lake at midday, calm blue water reflecting snow-capped peaks, "
    "gentle clouds drifting, soft sunlight, cinematic landscape, photorealistic"
)


def call(method, path, body=None, raw=False):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        BASE + path, data=data, method=method, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        payload = r.read()
    return payload if raw else json.loads(payload or b"{}")


start = call(
    "POST",
    "/api/v1/session/start",
    {"pipeline_id": "longlive", "input_mode": "text", "prompts": [{"text": PROMPT, "weight": 1.0}]},
)
print("start:", json.dumps(start)[:300], flush=True)

t0 = time.time()
n = 0
with open(os.path.join(OUT, "metrics.jsonl"), "w") as log:
    while time.time() - t0 < DURATION:
        time.sleep(10)
        n += 1
        t = round(time.time() - t0, 1)
        try:
            m = call("GET", "/api/v1/session/metrics")
        except Exception as e:
            m = {"error": str(e)}
        log.write(json.dumps({"t": t, "metrics": m}) + "\n")
        log.flush()
        print(t, json.dumps(m)[:400], flush=True)
        try:
            jpg = call("GET", "/api/v1/session/frame", raw=True)
            with open(os.path.join(OUT, f"frame_{n:02d}_{int(t)}s.jpg"), "wb") as f:
                f.write(jpg)
        except Exception as e:
            print("frame error:", e, flush=True)

print("stop:", call("POST", "/api/v1/session/stop"), flush=True)
