"""Send commands to the running server and check the arm REALLY moved (joint angles before/after),
instead of trusting the reply. Usage: python verify_moves.py "command 1" "command 2" ..."""
import json
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:8000"


def state():
    with urllib.request.urlopen(BASE + "/state", timeout=5) as r:
        return json.load(r)


def send(text):
    req = urllib.request.Request(BASE + "/api/command", data=json.dumps({"text": text}).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


for _ in range(60):
    s = state()
    if s["status"] in ("ready", "moving"):
        break
    print("waiting, arm is", s["status"], flush=True)
    time.sleep(1)
time.sleep(4)
for text in sys.argv[1:]:
    before = state()["measured"]
    reply = send(text)
    time.sleep(7)
    after = state()["measured"]
    moved = {k: round(after[k] - before[k]) for k in after if abs(after[k] - before[k]) >= 3}
    print(f"{text!r}: intents {reply.get('intents')} say {reply.get('say')!r}")
    print(f"    moved: {moved or 'NOTHING'}   status {state()['status']}", flush=True)
