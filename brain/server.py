"""Claude brain for the white SO-101: speak in any language, the arm does it (or shakes 'no').

  hold-to-talk page (or the Watcher's transcript) -> Whisper -> Claude plan -> executor -> arm
                                                                 \\-> spoken reply in the same language

Run (arm folded at rest, 12 V supply on):
  ../arm/.venv/bin/python server.py        then open http://127.0.0.1:8200
The Watcher bridge can post here too: receiver.py --voice --arm http://127.0.0.1:8200/api/command --token ...
"""
import os
import re
import sys
import threading
import time
from collections import deque
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response

import planner
import speech
import vision
from arm import Arm, ArmError
from executor import Executor

ROOT = Path(__file__).parent
# think and talk, but never move (weak supply, rehearsals)
DRY_RUN = "--dry-run" in sys.argv or os.environ.get("BRAIN_DRY_RUN") == "1"
# Spoken stop words act at once, without waiting for Claude.
STOP_WORDS = re.compile(r"^\W*(stop|para|pare|parar|chega|basta|alto|停|停下|停止|别动)\W*$", re.IGNORECASE)

app = FastAPI()
camera = vision.Camera()
events: deque = deque(maxlen=60)


def log(msg: str):
    events.append({"t": time.strftime("%H:%M:%S"), "msg": msg})
    print(msg, flush=True)


def say(text: str, lang: str):
    events.append({"t": time.strftime("%H:%M:%S"), "say": text, "lang": lang})
    speech.speak(text, lang)


arm = Arm()
executor = Executor(arm, camera, say=say, log=log)
log(f"arm ready, rest pose {arm.rest}")
threading.Thread(target=speech.warm_up, daemon=True).start()


def handle_text(text: str, source: str) -> dict:
    text = text.strip()
    if not text:
        return {"ok": False}
    log(f"[{source}] heard: {text}")
    if STOP_WORDS.match(text):
        executor.stop()
        return {"ok": True, "stopped": True}
    speech.chime()
    executor.stop()  # a new request replaces whatever was running
    t0 = time.time()
    try:
        plan = planner.plan(text, camera.jpeg(), arm.degrees())
    except Exception as e:  # network, rate limit, refusal
        log(f"planner error: {e}")
        say("Sorry, I could not think right now. Please try again.", "en")
        return {"ok": False, "error": str(e)}
    log(f"plan in {time.time() - t0:.1f}s ({plan['language']}, possible={plan['possible']}): "
        f"{[{k: v for k, v in a.items() if v is not None} for a in plan['actions']]}")
    say(plan["reply"], plan["language"])
    if DRY_RUN:
        log("dry run: arm not moved")
    else:
        threading.Thread(target=executor.run, args=(plan,), daemon=True).start()
    return {"ok": True, "plan": plan}


@app.get("/")
def index():
    return FileResponse(ROOT / "static" / "index.html")


@app.post("/audio")
async def audio(request: Request):
    data = await request.body()
    suffix = ".mp4" if "mp4" in request.headers.get("content-type", "") else ".webm"
    t0 = time.time()
    text, lang = speech.transcribe(data, suffix)
    log(f"whisper {time.time() - t0:.1f}s [{lang}]: {text}")
    return handle_text(text, "mic")


@app.post("/api/command")  # same shape as arm/panel.py, so watcher/arm_bridge.py can point here
async def command(request: Request):
    body = await request.json()
    if body.get("event") == "help_gesture":
        return handle_text("Someone showed an open palm asking for help: wave and say you are coming.", "watcher")
    return handle_text(body.get("text", ""), body.get("source", "api"))


@app.post("/stop")
def stop():
    executor.stop()
    log("STOP")
    return {"ok": True}


@app.post("/teach/{name}")
def teach(name: str):
    executor.teach_start()
    log(f"teach '{name}': torque off, hold the arm and put it in the pose")
    return {"ok": True}


@app.post("/save/{name}")
def save(name: str):
    pose = executor.teach_save(name)
    log(f"saved pose '{name}': {pose}")
    return {"ok": True, "pose": pose}


@app.post("/rest")
def rest():
    def go():
        try:
            executor.go_pose("rest")
            arm.release()
            log("at rest, torque off")
        except ArmError as e:
            log(f"arm error: {e}")
    threading.Thread(target=go, daemon=True).start()
    return {"ok": True}


@app.get("/state")
def state():
    try:
        joints = arm.degrees()
    except ArmError as e:
        joints = {"error": str(e)}
    return JSONResponse({"joints": joints, "torque": arm.torque, "busy": executor.busy.locked(),
                         "events": list(events)[-25:], "model": planner.MODEL})


@app.get("/camera.jpg")
def camera_jpg():
    data = camera.jpeg(size=(640, 360), quality=70)
    return Response(data or b"", media_type="image/jpeg", status_code=200 if data else 503)


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8200, log_level="warning")
