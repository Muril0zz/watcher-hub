"""Voice-controlled arm server: owns the SO-101 connection, a 30 Hz motion loop and the camera.

The browser transcribes speech and posts the text; commands.py turns it into intents that move a
small "arm state" (base angle, height, wrist, gripper). The loop walks the real arm toward that
state at the current speed. Rising joints are capped and staged (forearm before shoulder) so the
5 V supply does not brown out; if it does anyway, the arm stands back up by itself.

Any language: hold-to-talk audio goes through local Whisper, then Claude (claude_intents.py) maps
whatever was said onto these intents and writes the reply, spoken by the Mac in the same language.
Typed text takes the same path; the keyword parser in commands.py is the fallback when Claude is
unreachable.

Run: python server.py [PORT] [ID]   then open http://localhost:8000
"""
import json
import re
import sys
import threading
import time
from collections import deque
from pathlib import Path

import cv2
import numpy as np
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel

import claude_intents
import routing
import speech
from commands import Intent, parse
from crazy_show import Performer, make_robot, routine
from show import HZ, JOINTS, SKY
from stand_up import stand_up

ROOT = Path(__file__).parent
SETTINGS_FILE = ROOT / "settings.json"
PORT = sys.argv[1] if len(sys.argv) > 1 else "/dev/tty.usbmodem5B790830241"
ROBOT_ID = sys.argv[2] if len(sys.argv) > 2 else "preto"

LOW = {"shoulder_lift": 35.0, "elbow_flex": -45.0, "wrist_flex": 45.0}  # the bow: lowest pose it rises from
LIFT_JOINTS = ("shoulder_lift", "elbow_flex")
LIFT_SPEED_CAP = 45.0  # deg/s on joints that fight gravity (5 V / 3 A supply)
AUTO_STAND_MAX = 70.0  # shoulder_lift above this (lying forward) is too heavy to lift without a hand
SPEED_RANGE = (10.0, 160.0)
# pan stops short of the base's end stop: parked at 110 deg it stuck there and tripped the contact guard
PAN_LIMIT, ROLL_LIMIT, WRIST_LIMIT = 95.0, 170.0, 40.0
CONTACT_LOAD = 800  # 0..1000: straining this hard without moving = touching something (the table)
STOP_WORDS = re.compile(r"^\W*(stop|para|pare|parar|chega|basta|alto|停|停下|停止|别动)\W*$", re.IGNORECASE)
CAMERA_HFOV = 60.0  # degrees, Mac FaceTime camera, approx.

HSV = {
    "green": [((35, 80, 60), (85, 255, 255))],
    "red": [((0, 120, 70), (10, 255, 255)), ((170, 120, 70), (180, 255, 255))],
    "blue": [((95, 120, 60), (130, 255, 255))],
    "yellow": [((20, 120, 100), (34, 255, 255))],
}
COLOR_NAMES = {"green": ("verde", "green"), "red": ("vermelho", "red"), "blue": ("azul", "blue"), "yellow": ("amarelo", "yellow")}
HOME = {"pan": 0.0, "h": 1.0, "wflex": 0.0, "roll": 0.0, "grip": 50.0}


class StopShow(Exception):
    pass


class Camera:
    """Keeps the latest frame; color lookups and the UI preview read from it."""

    def __init__(self, index=0):
        self.lock = threading.Lock()
        self.frame = None
        self.mark = None  # (color, box, center) of the last lookup, drawn on the preview
        threading.Thread(target=self._run, args=(index,), daemon=True).start()

    def _run(self, index):
        cap = cv2.VideoCapture(index)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        while True:
            ok, frame = cap.read()
            if ok:
                with self.lock:
                    self.frame = frame
            time.sleep(0.05)

    def locate(self, color):
        """Normalized x (0 left .. 1 right) of the biggest blob of `color`, or None."""
        with self.lock:
            frame = None if self.frame is None else self.frame.copy()
        if frame is None:
            return None
        hsv = cv2.cvtColor(cv2.GaussianBlur(frame, (9, 9), 0), cv2.COLOR_BGR2HSV)
        mask = np.zeros(hsv.shape[:2], np.uint8)
        for lo, hi in HSV[color]:
            mask |= cv2.inRange(hsv, np.array(lo), np.array(hi))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None
        biggest = max(contours, key=cv2.contourArea)
        if cv2.contourArea(biggest) < 0.002 * mask.size:
            return None
        x, y, w, h = cv2.boundingRect(biggest)
        cx = (x + w / 2) / frame.shape[1]
        self.mark = (color, (x, y, w, h), time.time())
        return cx

    def jpeg(self):
        with self.lock:
            frame = None if self.frame is None else self.frame.copy()
        if frame is None:
            return None
        if self.mark and time.time() - self.mark[2] < 4:
            x, y, w, h = self.mark[1]
            cv2.rectangle(frame, (x, y), (x + w, y + h), (80, 255, 80), 6)
        frame = cv2.resize(frame, (640, int(640 * frame.shape[0] / frame.shape[1])))
        return cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])[1].tobytes()


class Arm:
    def __init__(self, port, robot_id):
        self.port, self.robot_id = port, robot_id
        self.lock = threading.Lock()
        self.settings = {"speed": 40.0, "invert": False}
        if SETTINGS_FILE.exists():
            self.settings.update(json.loads(SETTINGS_FILE.read_text()))
        self.state = dict(HOME)
        self.queue = deque()
        self.status = "starting"
        self.measured = {}
        self.cmd = None
        self.robot = None
        self.show_requested = False
        self.stop_requested = False
        self.hold = False  # frozen after touching something, until the next command
        self.seq = 0  # bumped by every new command: a running multi-step sequence stops when it changes
        self.lang = "pt"
        self.events = deque(maxlen=40)
        threading.Thread(target=self._run, daemon=True).start()

    def log(self, msg: str, say: str | None = None):
        self.events.append({"t": time.strftime("%H:%M:%S"), "msg": msg, "say": say})
        print(msg, flush=True)

    # ---- state the loop walks toward -------------------------------------------------------
    def target_pose(self):
        s = self.state
        h = s["h"]
        lift = {j: LOW[j] + (SKY[j] - LOW[j]) * h for j in LOW}
        return {
            "shoulder_pan": s["pan"],
            "shoulder_lift": lift["shoulder_lift"],
            "elbow_flex": lift["elbow_flex"],
            "wrist_flex": lift["wrist_flex"] + s["wflex"],
            "wrist_roll": s["roll"],
            "gripper": s["grip"],
        }

    def save_settings(self):
        SETTINGS_FILE.write_text(json.dumps(self.settings, indent=2))

    # ---- motion loop ---------------------------------------------------------------------
    def _connect(self):
        self.status = "connecting"
        if self.robot is not None:
            try:
                self.robot.bus.port_handler.closePort()
            except Exception:
                pass
        self._wait_inside_limits()
        self.robot = make_robot(self.port, self.robot_id)
        obs = self.robot.get_observation()
        lift = obs["shoulder_lift.pos"]
        if lift > AUTO_STAND_MAX:
            # too low to lift on this supply: go limp and wait for a person to stand it up by hand
            self.robot.bus.disable_torque()
            self.status = "lying"
            while obs["shoulder_lift.pos"] > 15 or obs["elbow_flex.pos"] > -60:
                time.sleep(0.3)
                obs = self.robot.get_observation()
                self.measured = {j: round(obs[f"{j}.pos"], 1) for j in JOINTS}
            self.robot.bus.enable_torque()
        elif lift > 20:  # moderately low: the staged stand-up handles it
            self.robot.disconnect()
            stand_up(self.port, self.robot_id)
            self.robot = make_robot(self.port, self.robot_id)
            obs = self.robot.get_observation()
        self.cmd = {j: obs[f"{j}.pos"] for j in JOINTS}
        self.measured = dict(self.cmd)
        with self.lock:
            self.state = {**HOME, "pan": self.cmd["shoulder_pan"], "grip": self.cmd["gripper"]}
            self.queue.clear()
        self.status = "ready"

    def _wait_inside_limits(self):
        """Torque on with a joint outside the servo's own limits makes it jump to the limit: wait (limp)
        until every joint is inside, e.g. after the arm was moved by hand or re-assembled."""
        import scservo_sdk as scs

        port, pk = scs.PortHandler(self.port), scs.PacketHandler(0)
        port.openPort()
        port.setBaudRate(1_000_000)
        try:
            while True:
                outside = []
                for name, i in (("shoulder_pan", 1), ("shoulder_lift", 2), ("elbow_flex", 3), ("wrist_flex", 4)):
                    pos = pk.read2ByteTxRx(port, i, 56)[0]
                    lo, hi = pk.read2ByteTxRx(port, i, 9)[0], pk.read2ByteTxRx(port, i, 11)[0]
                    if not lo - 30 <= pos <= hi + 30:
                        outside.append(name)
                if not outside:
                    return
                self.status = "lying"
                self.log(f"outside its range: {outside}; move it into range by hand")
                time.sleep(1.0)
        finally:
            port.closePort()

    def _recover(self):
        """After a brownout the servos reboot limp; reconnect and let _connect decide how to stand."""
        self.status = "recovering"
        try:
            self.robot.bus.port_handler.closePort()
        except Exception:
            pass
        for attempt in range(10):
            time.sleep(1.5)
            try:
                self._connect()
                return
            except ConnectionError as exc:
                print(f"reconnect attempt {attempt + 1} failed: {exc}", flush=True)
        raise RuntimeError("arm did not come back")

    def _run(self):
        while True:
            try:
                if self.robot is None:
                    self._connect()
                self._loop()
            except ConnectionError as exc:
                print(f"BROWNOUT: {exc}", flush=True)
                try:
                    self._recover()
                except Exception as exc2:
                    print(f"recover failed: {exc2}", flush=True)
                    self.status = "offline"
                    self.robot = None
                    time.sleep(3)
            except Exception as exc:
                print(f"arm offline: {exc}", flush=True)
                self.status = "offline"
                self.robot = None
                time.sleep(3)

    def _loop(self):
        tick = 0
        while True:
            if self.show_requested:
                self._run_show()
            with self.lock:
                target = self.target_pose() if not self.hold else dict(self.cmd)
                speed = self.settings["speed"]
            new = {}
            for j in JOINTS:
                cur, goal = self.cmd[j], target[j]
                if j == "gripper":
                    rate = speed * 3
                elif j in LIFT_JOINTS:
                    rate = min(speed, LIFT_SPEED_CAP)
                else:
                    rate = speed
                # rising: forearm first, the shoulder waits until the elbow is nearly there
                if j == "shoulder_lift" and goal < cur and self.cmd["elbow_flex"] > target["elbow_flex"] + 5:
                    goal = cur
                step = rate / HZ
                new[j] = cur + max(-step, min(step, goal - cur))
            self.cmd = new
            self.robot.send_action({f"{j}.pos": v for j, v in new.items()})
            tick += 1
            if tick % 6 == 0:
                obs = self.robot.get_observation()
                before = self.measured
                self.measured = {j: round(obs[f"{j}.pos"], 1) for j in JOINTS}
                self._guard_contact(before, target)
            arrived = all(abs(new[j] - target[j]) < 1.0 for j in JOINTS)
            if arrived and self.queue:
                with self.lock:
                    self.state.update(self.queue.popleft())
            self.status = "moving" if not arrived else "ready"
            time.sleep(1 / HZ)

    def _guard_contact(self, before: dict, target: dict):
        """Straining hard while not moving toward the goal = touching something: freeze right there."""
        if self.hold or not before:
            return
        try:
            loads = self.robot.bus.sync_read("Present_Load", normalize=False)
        except Exception:
            return
        # the base turns flat (it can't hit the table) and its end-stop friction gave false alarms
        strain = getattr(self, "strain", {})
        self.strain = strain
        for j in ("shoulder_lift", "elbow_flex", "wrist_flex"):
            far = abs(self.measured[j] - target[j]) > 3
            still = abs(self.measured[j] - before.get(j, self.measured[j])) < 0.5
            # a motion's first instant is all load and no movement yet: only ~0.6 s of it means contact
            strain[j] = strain.get(j, 0) + 1 if (far and still and (loads[j] & 0x3FF) >= CONTACT_LOAD) else 0
            if strain[j] >= 3:
                strain.clear()
                with self.lock:
                    self.hold = True
                    self.queue.clear()
                self.cmd = {k: self.measured[k] for k in JOINTS}
                msg = {"pt": "Encostei em alguma coisa e parei.", "en": "I touched something and stopped.",
                       "zh": "我碰到了东西，已经停下了。", "es": "Toqué algo y me detuve."}
                text = msg.get(self.lang[:2], msg["en"])
                self.log(f"contact on {j} (load {loads[j] & 0x3FF})", say=text)
                speech.speak(text, self.lang)
                return

    def _run_show(self):
        self.show_requested = False
        self.stop_requested = False
        self.status = "show"
        arm = self

        class ShowPerformer(Performer):
            def send(self, pose):
                if arm.stop_requested:
                    raise StopShow
                super().send(pose)

        def revive():
            arm._recover()
            return arm.robot

        performer = ShowPerformer(self.robot, revive)
        try:
            routine(performer)
        except StopShow:
            pass
        self.robot = performer.robot
        obs = self.robot.get_observation()
        self.cmd = {j: obs[f"{j}.pos"] for j in JOINTS}
        with self.lock:
            self.state = {**HOME, "pan": self.cmd["shoulder_pan"], "grip": self.cmd["gripper"]}
            self.queue.clear()

    # ---- commands ------------------------------------------------------------------------
    def apply(self, intent: Intent, lang: str, camera: Camera) -> str:
        pt = lang != "en"
        s = self.state
        # big on purpose: moves have to read from across a room (doubled for the demo)
        step_pan = {"little": 20.0, "normal": 50.0, "max": PAN_LIMIT}[intent.amount]
        if intent.degrees:
            step_pan = intent.degrees
        step_h = {"little": 0.2, "normal": 0.5, "max": 1.0}[intent.amount]
        sign = -1.0 if self.settings["invert"] else 1.0
        clamp = lambda v, lim: max(-lim, min(lim, v))
        name = intent.name

        with self.lock:
            if self.hold and name != "stop":
                # leave the frozen pose from where the arm actually is
                self.hold = False
            if name != "stop" and self.queue:
                # a new command cuts a gesture short: put the gesture's joint back where it ends
                for frame in self.queue:
                    s.update(frame)
                self.queue.clear()
            if name == "stop":
                self.stop_requested = True
                self.queue.clear()
                cur = self.cmd or {}
                if cur:
                    s.update(pan=cur["shoulder_pan"], roll=cur["wrist_roll"], grip=cur["gripper"])
                return "Parei." if pt else "Stopped."
            if name in ("left", "right"):
                direction = 1.0 if name == "left" else -1.0
                if intent.amount == "max" and not intent.degrees:
                    s["pan"] = sign * direction * PAN_LIMIT
                else:
                    s["pan"] = clamp(s["pan"] + sign * direction * step_pan, PAN_LIMIT)
                return ("Virando para a " + ("esquerda" if name == "left" else "direita")) if pt else f"Turning {name}"
            if name == "side":
                s["pan"] = -80.0 if s["pan"] >= 0 else 80.0
                return "Indo para o lado" if pt else "Going to the side"
            if name == "center":
                s.update(pan=0.0, wflex=0.0, roll=0.0)
                return "Voltando para o centro" if pt else "Back to center"
            if name == "home":
                s.update(HOME)
                return "Em pé" if pt else "Standing up"
            if name in ("up", "down"):
                s["h"] = max(0.0, min(1.0, s["h"] + (step_h if name == "up" else -step_h)))
                s["wflex"] = 0.0
                return ("Subindo" if name == "up" else "Descendo") if pt else ("Going up" if name == "up" else "Going down")
            if name == "open":
                s["grip"] = 100.0
                return "Abrindo a garra" if pt else "Opening the gripper"
            if name == "close":
                s["grip"] = 0.0
                return "Fechando a garra" if pt else "Closing the gripper"
            if name == "roll_full":
                for r in (ROLL_LIMIT, -ROLL_LIMIT, 0.0):
                    self.queue.append({"roll": r})
                return "Girando o punho todo" if pt else "Turning the wrist all the way"
            if name in ("wrist_up", "wrist_down"):
                d = 40.0 if name == "wrist_up" else -40.0
                s["wflex"] = clamp(s["wflex"] + d, WRIST_LIMIT)
                return "Mexendo a mão" if pt else "Tilting the hand"
            if name == "spin":
                s["roll"] = s["roll"] + 90 if s["roll"] + 90 <= ROLL_LIMIT else s["roll"] - 90
                return "Girando o punho" if pt else "Spinning the wrist"
            if name in ("wave", "shake", "nod"):
                base = dict(s)
                key, amp, times = {"wave": ("roll", 70, 3), "shake": ("roll", 60, 3), "nod": ("wflex", 40, 2)}[name]
                for _ in range(times):
                    self.queue.append({key: clamp(base[key] + amp, ROLL_LIMIT if key == "roll" else WRIST_LIMIT)})
                    self.queue.append({key: clamp(base[key] - amp, ROLL_LIMIT if key == "roll" else WRIST_LIMIT)})
                self.queue.append({key: base[key]})
                if name == "wave":
                    self.queue.appendleft({"grip": 100.0})  # wave at the current height (keeps an earlier "down")
                return {"wave": ("Olá!", "Hello!"), "shake": ("Não, não", "No, no"), "nod": ("Sim!", "Yes!")}[name][0 if pt else 1]
            if name in ("faster", "slower"):
                factor = 1.5 if name == "faster" else 1 / 1.5
                lo, hi = SPEED_RANGE
                self.settings["speed"] = max(lo, min(hi, self.settings["speed"] * factor))
                self.save_settings()
                pct = round(self.settings["speed"] / 40 * 100)
                return (f"Velocidade {pct}%" if pt else f"Speed {pct}%")
            if name == "invert":
                self.settings["invert"] = not self.settings["invert"]
                self.save_settings()
                return "Invertido: esquerda e direita trocadas" if pt else "Left and right swapped"
            if name == "show":
                self.show_requested = True
                return "Lá vai o show!" if pt else "Showtime!"

        if name == "goto_color":
            cx = camera.locate(intent.color)
            label = COLOR_NAMES[intent.color][0 if pt else 1]
            if cx is None:
                return f"Não estou vendo nada {label}" if pt else f"I can't see anything {label}"
            with self.lock:
                s["pan"] = clamp(sign * (0.5 - cx) * CAMERA_HFOV, PAN_LIMIT)
                s.update(h=0.35, wflex=0.0, grip=100.0)
            return f"Indo até o {label}" if pt else f"Going to the {label}"
        return "Não entendi" if pt else "I didn't get that"

    def snapshot(self):
        return {
            "status": self.status,
            "speed": round(self.settings["speed"]),
            "speed_pct": round(self.settings["speed"] / 40 * 100),
            "invert": self.settings["invert"],
            "measured": self.measured,
            "target": {k: round(v, 1) for k, v in self.target_pose().items()},
        }


app = FastAPI()
camera = Camera()
arm = Arm(PORT, ROBOT_ID)


class CommandIn(BaseModel):
    text: str = ""
    intent: str | None = None
    amount: str = "normal"
    color: str | None = None
    lang: str = "pt"


@app.get("/")
def index():
    return FileResponse(ROOT / "static" / "index.html")


def wait_settled(seq: int, timeout: float = 12.0) -> bool:
    """Wait until the arm has reached the current target and finished any gesture. False if a newer
    command (or stop) took over meanwhile."""
    time.sleep(0.2)  # let the loop pick up the new target
    end, calm = time.time() + timeout, 0
    while time.time() < end:
        if arm.seq != seq:
            return False
        busy = arm.queue or arm.show_requested or arm.status in ("moving", "show")
        calm = 0 if busy else calm + 1
        if calm >= 3:
            return True
        time.sleep(0.1)
    return arm.seq == seq


def run_sequence(intents: list, lang: str, seq: int):
    """Several instructions in one sentence: one after the other, each waiting for the arm to arrive."""
    for n, intent in enumerate(intents):
        if arm.seq != seq:
            return
        arm.apply(intent, lang, camera)
        if n < len(intents) - 1 and not wait_settled(seq):
            return


def start_sequence(intents: list, lang: str):
    arm.seq += 1
    if len(intents) <= 1:
        for i in intents:
            arm.apply(i, lang, camera)
        return
    threading.Thread(target=run_sequence, args=(intents, lang, arm.seq), daemon=True).start()


ENGLISH = re.compile(r"\b(turn|go|left|right|up|down|wave|open|close|stop|the|please|move|all|way|a bit|hand|arm)\b",
                     re.IGNORECASE)
CONFIRM = {  # short spoken confirmations for the instant path
    "left": ("Virando para a esquerda", "Turning left"), "right": ("Virando para a direita", "Turning right"),
    "up": ("Subindo", "Going up"), "down": ("Descendo", "Going down"), "center": ("Ao centro", "Back to center"),
    "home": ("Em pé", "Standing up"), "side": ("Para o lado", "To the side"), "open": ("Abrindo", "Opening"),
    "close": ("Fechando", "Closing"), "spin": ("Girando o punho", "Turning the wrist"),
    "roll_full": ("Girando o punho todo", "Full wrist turn"), "wave": ("Olá!", "Hello!"), "nod": ("Sim!", "Yes!"),
    "shake": ("Não!", "No!"), "show": ("Lá vai o show!", "Showtime!"), "faster": ("Mais rápido", "Faster"),
    "slower": ("Mais devagar", "Slower"), "stop": ("Parei", "Stopped"), "wrist_up": ("Mão para cima", "Hand up"),
    "wrist_down": ("Mão para baixo", "Hand down"), "invert": ("Lados trocados", "Sides swapped"),
}


def confirmation(intents, lang: str) -> str:
    pt = (lang or "pt")[:2] != "en"
    parts = []
    for i in intents:
        words = CONFIRM.get(i.name)
        if words:
            text = words[0 if pt else 1]
            if i.amount == "max" and i.name in ("left", "right", "up", "down"):
                text += " até o fim" if pt else " all the way"
            parts.append(text)
    return ", ".join(parts) or ("Ok" if pt else "OK")


def handle_text(text: str, lang_hint: str = "pt", quiet: bool = False, addressed: bool = False) -> dict:
    """Any language: Claude picks the intents and the reply; the keyword parser is the offline fallback.
    quiet: don't speak on the Mac (the Watcher answers out loud itself)."""
    speak = (lambda *a, **k: None) if quiet else speech.speak
    text = text.strip()
    if not text:
        return {"heard": text, "intents": [], "say": ""}
    if STOP_WORDS.match(text):
        arm.seq += 1  # cancels a running sequence
        arm.apply(Intent("stop"), lang_hint, camera)
        arm.log(f"heard: {text} -> STOP")
        return {"heard": text, "intents": ["stop"], "say": ""}
    if arm.status not in ("ready", "moving"):
        # never answer "sure!" while the arm can't move
        msg = {"pt": "Ainda não estou pronto para me mexer.", "en": "I'm not ready to move yet.",
               "zh": "我还没准备好，暂时不能动。", "es": "Todavía no estoy listo para moverme."}
        say = msg.get((lang_hint or "pt")[:2], msg["en"])
        arm.log(f"heard: {text} -> refused, arm is {arm.status}", say=say)
        speak(say, lang_hint or "pt")
        return {"heard": text, "intents": [], "say": say, "spoken": True, "status": arm.status}
    # Fast path: short, plain commands the keyword parser fully understands run at once, no API round trip.
    intents = routing.fast_intents(text, lang_hint)
    if intents is not None:
        lang = (lang_hint or "pt")[:2]
        start_sequence(intents, lang)
        say = confirmation(intents, lang)
        arm.lang = lang
        arm.log(f"heard: {text} -> fast {[i.name for i in intents]}", say=say)
        speak(say, lang)
        return {"heard": text, "intents": [i.name for i in intents], "say": say, "spoken": True, "language": lang}
    t0 = time.time()
    try:
        plan = claude_intents.plan(text, addressed=addressed)
    except Exception as e:
        arm.log(f"Claude unavailable ({e}); keyword fallback")
        intents = parse(text).intents
        start_sequence(intents, lang_hint)
        say = "Ok" if intents else "Não entendi"
        speak(say, "pt")
        return {"heard": text, "intents": [i.name for i in intents], "say": say, "spoken": True}
    if not addressed and not plan.get("for_robot", True):
        arm.log(f"ignored (not for the robot): {text}")
        return {"heard": text, "intents": [], "say": "", "spoken": True, "ignored": True}
    lang = plan["language"] or lang_hint
    arm.lang = lang
    names = [i["name"] for i in plan["intents"]]
    arm.log(f"heard: {text} -> {lang} {names} ({time.time() - t0:.1f}s)", say=plan["reply"])
    speak(plan["reply"], lang)
    start_sequence([Intent(i["name"], amount=i["amount"], degrees=i["degrees"]) for i in plan["intents"]], lang)
    return {"heard": text, "intents": names, "say": plan["reply"], "spoken": True, "language": lang}


@app.post("/command")
def command(body: CommandIn):
    if body.intent:  # page buttons: no need to ask Claude
        arm.seq += 1
        replies = [arm.apply(Intent(body.intent, amount=body.amount, color=body.color), body.lang, camera)]
        return {"heard": body.text, "intents": [body.intent], "say": ". ".join(replies)}
    return handle_text(body.text, body.lang)


@app.post("/api/command")  # same shape as the Watcher bridge sends
async def api_command(request: Request):
    body = await request.json()
    text = body.get("text", "")
    if body.get("source") == "marco-mcp":
        # Marco's cloud called its move_arm tool (marco_mcp.py): it is addressed to the arm and Marco
        # answers out loud itself, so the Mac stays quiet
        if re.search(r"[一-鿿]", text):
            lang = "zh"
        elif ENGLISH.search(text):
            lang = "en"
        else:
            lang = "pt"
        return handle_text(text, lang, quiet=True, addressed=True)
    return handle_text(text)


@app.post("/audio")
async def audio(request: Request):
    data = await request.body()
    suffix = ".mp4" if "mp4" in request.headers.get("content-type", "") else ".webm"
    t0 = time.time()
    text, lang = speech.transcribe(data, suffix)
    if not text:
        arm.log(f"whisper {time.time() - t0:.1f}s: noise or silence, ignored")
        return {"heard": "", "intents": [], "say": "", "spoken": True, "ignored": True}
    arm.log(f"whisper {time.time() - t0:.1f}s [{lang}]: {text}")
    return handle_text(text, lang or "pt")


@app.get("/state")
def state():
    return JSONResponse({**arm.snapshot(), "events": list(arm.events)[-20:]})


@app.get("/camera.jpg")
def camera_jpg():
    data = camera.jpeg()
    return Response(data or b"", media_type="image/jpeg", status_code=200 if data else 503)


WATCHER_HEARD = re.compile(r"Application: >> (.+?)\s*$")
WAKE_WORDS = {"marco", "你好小智", "小智", "hi esp", "hey marco"}
WATCHER_QUIET = "--watcher-quiet" in sys.argv  # default: the Mac speaks the reply for Watcher commands
# one-word answers to Marco's own questions ("Yes." made the arm nod): conversation, not commands
SMALL_TALK = {"yes", "no", "ok", "okay", "yeah", "yep", "nope", "sure", "thanks", "thank you", "sim", "não", "nao",
              "tá", "ta", "beleza", "好", "好的", "是", "是的", "不", "不是", "对", "嗯", "谢谢"}


def watcher_bridge():
    """SenseCAP Watcher (XiaoZhi firmware) over USB: its console logs 'Application: >> <what it heard>'.
    Feed those lines to the same brain; the Watcher's own assistant does the talking."""
    import serial
    from serial.tools import list_ports

    while True:
        ports = [p.device for p in list_ports.comports() if (p.vid, p.pid) == (0x1A86, 0x55D2)]
        if not ports:
            time.sleep(3)
            continue
        for dev in sorted(ports, reverse=True):  # the ESP32 console is the higher-numbered one
            try:
                with serial.Serial(dev, 115200, timeout=1) as port:
                    arm.log(f"watcher bridge listening on {dev}")
                    while True:
                        line = port.readline().decode("utf-8", "replace")
                        m = WATCHER_HEARD.search(line)
                        if not m:
                            continue
                        heard = m.group(1).strip()
                        if heard.lower().strip(" .!?。！") in WAKE_WORDS:
                            continue
                        if heard.lower().strip(" .!?,。！，") in SMALL_TALK:
                            arm.log(f"[watcher] {heard} (answer to Marco, not a command)")
                            continue
                        if re.search(r"[\u4e00-\u9fff]", heard):
                            lang = "zh"
                        elif ENGLISH.search(heard):
                            lang = "en"
                        else:
                            lang = "pt"
                        arm.log(f"[watcher] {heard}")
                        # the Mac answers (Marco's cloud assistant doesn't know about the arm and says it can't
                        # move it): turn Marco's knob all the way down and let the arm's own voice reply
                        threading.Thread(target=handle_text, args=(heard, lang, WATCHER_QUIET, True), daemon=True).start()
            except Exception as e:  # unplugged, busy, reset: try again
                arm.log(f"watcher bridge: {e}")
                time.sleep(3)


threading.Thread(target=speech.warm_up, daemon=True).start()
if "--no-watcher" not in sys.argv:
    threading.Thread(target=watcher_bridge, daemon=True).start()
threading.Thread(target=claude_intents.keep_warm, daemon=True).start()

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")
