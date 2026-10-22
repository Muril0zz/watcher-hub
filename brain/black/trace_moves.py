"""Send one command and print the joints every 0.5 s, to see multi-step requests happen in order.
Usage: python trace_moves.py "command" [seconds]"""
import json
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:8000"
JOINTS = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper")


def state():
    with urllib.request.urlopen(BASE + "/state", timeout=5) as r:
        return json.load(r)


while state()["status"] not in ("ready", "moving"):
    time.sleep(1)
time.sleep(3)
text, seconds = sys.argv[1], float(sys.argv[2]) if len(sys.argv) > 2 else 16
req = urllib.request.Request(BASE + "/api/command", data=json.dumps({"text": text}).encode(),
                             headers={"Content-Type": "application/json"}, method="POST")
t0 = time.time()
with urllib.request.urlopen(req, timeout=30) as r:
    reply = json.load(r)
print(f"{text!r} -> {reply.get('intents')} {reply.get('say')!r}  ({time.time() - t0:.1f}s)")
print("   t    " + " ".join(f"{j[:8]:>8}" for j in JOINTS) + "  status")
while time.time() - t0 < seconds:
    s = state()
    m = s["measured"]
    print(f"{time.time() - t0:5.1f} " + " ".join(f"{m.get(j, 0):8.0f}" for j in JOINTS) + f"  {s['status']}", flush=True)
    time.sleep(0.5)
