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
import watcher_link
from arm import DISABLED, Arm, ArmError
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
    if source == "marco-mcp" and executor.busy.locked():
        # Marco fires follow-up calls while the arm is still moving the cup; only "stop" may cut it short
        log("[marco] busy: request ignored")
        return {"ok": True, "say": "One moment, I'm still moving."}
    if source != "marco-mcp":
        speech.chime()
    executor.stop()  # a new request replaces whatever was running
    t0 = time.time()
    prompt = text + (watcher_link.NOTE if source == "watcher" else "")
    try:
        plan = planner.plan(prompt, camera.jpeg(), arm.degrees(), sorted(DISABLED))
    except Exception as e:  # network, rate limit, refusal
        log(f"planner error: {e}")
        say("Sorry, I could not think right now. Please try again.", "en")
        return {"ok": False, "error": str(e)}
    log(f"plan in {time.time() - t0:.1f}s ({plan['language']}, possible={plan['possible']}): "
        f"{[{k: v for k, v in a.items() if v is not None} for a in plan['actions']]}")
    if source == "marco-mcp":
        # Marco called its move_arm tool over Wi-Fi and speaks what we return; the Mac stays quiet
        return {"ok": True, "plan": plan, "say": run_for_marco(plan)}
    say(plan["reply"], plan["language"])
    if DRY_RUN:
        log("dry run: arm not moved")
    else:
        threading.Thread(target=executor.run, args=(plan,), daemon=True).start()
    return {"ok": True, "plan": plan}


def run_for_marco(plan: dict) -> str:
    """A look is waited for, so Marco can say what is on the table; longer moves run in the background
    and Marco just says the reply."""
    log(f"[marco] {plan['reply']}")
    if DRY_RUN:
        return plan["reply"]
    if plan["actions"] and all(a["type"] == "look" for a in plan["actions"]):
        spoken = []
        old = executor.say
        executor.say = lambda text, lang: (spoken.append(text), log(f"[marco says] {text}"))
        try:
            executor.run(plan)
        finally:
            executor.say = old
        return " ".join(spoken) or plan["reply"]
    quiet = executor.say
    threading.Thread(target=_run_quiet, args=(plan, quiet), daemon=True).start()
    return plan["reply"]


def _run_quiet(plan: dict, restore):
    executor.say = lambda text, lang: log(f"[marco] {text}")  # failures are logged, Marco already answered
    try:
        executor.run(plan)
    finally:
        executor.say = restore


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


@app.post("/spot")
def spot():
    """Demo setup: lower the open gripper, turned as for grabbing, onto the front cup spot, so the cup can
    be placed exactly between the jaws."""
    def go():
        try:
            from executor import CUP_SPOT, GRAB_ROLL
            x, z = CUP_SPOT
            arm.move_deg({"wrist_roll": 0, "shoulder_pan": 0, "gripper": 100})
            executor._level_to(x, z + 0.08, steps=3)
            executor._level_to(x, z, steps=2)
            arm.move_deg({"wrist_roll": GRAB_ROLL}, timeout=4)
            executor.cup_pan = 0
            log("at the cup spot: place the cup between the jaws")
        except ArmError as e:
            log(f"arm error: {e}")
    threading.Thread(target=go, daemon=True).start()
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


if "--watcher" in sys.argv:  # Marco -> this arm (stop the black-arm server's bridge: one port, one reader)
    watcher_link.start(lambda heard: handle_text(heard, "watcher"), log)

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8200, log_level="warning")
