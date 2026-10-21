#!/usr/bin/env python3
"""
Control a SenseCAP Watcher (factory SenseCraft firmware) from your computer
through its USB-C serial console (the `SenseCAP>` prompt).

Pairs with watcher/receiver.py: this script loads a task flow onto the
Watcher, and the task's "http alarm" block pushes alarms to the receiver.

One-time setup in the SenseCraft app:
  Settings > HTTP Message Block > URL = http://<laptop-LAN-IP>:8887 (token optional)
  (that is where every "http alarm" block sends its POST)

Usage (pip install pyserial):
  python3 watcher/control.py ports                  # find the Watcher's serial port
  python3 watcher/control.py -p PORT load person    # built-in preset
  python3 watcher/control.py -p PORT load my.json   # your own task flow file
  python3 watcher/control.py -p PORT export         # print the running task flow
  python3 watcher/control.py -p PORT add-http       # make the running task (e.g. made by voice) push to the receiver
  python3 watcher/control.py -p PORT battery
  python3 watcher/control.py -p PORT rgb 255 0 0    # LED colour
  python3 watcher/control.py -p PORT cmd "help"     # any console command
  python3 watcher/control.py -p PORT monitor        # stream the device log

The USB-C port usually shows up as TWO serial ports (ESP32 + Himax AI chip).
The console is on the ESP32 one: if `battery` prints nothing, try the other.
Presets: person, gesture (open palm = "call for help"), pet.
"""
import argparse
import json
import re
import sys
import time

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    sys.exit("Needs pyserial:  pip install pyserial")

# --------------------------------------------------------------------------
# Task-flow presets. model_type: 1 = person, 2 = pet, 3 = gesture (built-in
# Himax models, no download). Each alarm goes to: HTTP push (to your laptop),
# UART (Grove port) and the Watcher's own LED + sound.
# --------------------------------------------------------------------------
PRESETS = {
    "person":  {"model_type": 1, "cls": "person", "text": "Person detected"},
    "gesture": {"model_type": 3, "cls": "paper",  "text": "Open palm: help requested"},
    "pet":     {"model_type": 2, "cls": "dog",    "text": "Pet detected"},
}


def build_flow(model_type: int, cls: str, text: str, conf: int = 65,
               silence: int = 5, tlid: int | None = None) -> dict:
    tlid = tlid or int(time.time() * 1000)
    return {
        "tlid": tlid, "ctd": tlid, "tn": text, "type": 0,
        "task_flow": [
            {"id": 1, "type": "ai camera", "index": 0, "version": "1.0.0",
             "params": {"model_type": model_type, "modes": 0,
                        "model": {"arguments": {"iou": 45, "conf": conf}},
                        # mode 1 + type 2 + num 0  =>  "count of <cls> > 0"
                        "conditions": [{"class": cls, "mode": 1, "type": 2, "num": 0}],
                        "conditions_combo": 0,
                        "silent_period": {"silence_duration": silence},
                        "output_type": 0, "shutter": 0},
             "wires": [[2]]},
            {"id": 2, "type": "alarm trigger", "index": 1, "version": "1.0.0",
             "params": {"text": text, "audio": ""},
             "wires": [[3, 4, 5]]},
            {"id": 3, "type": "http alarm", "index": 2, "version": "1.0.0",
             "params": {"silence_duration": silence, "time_en": 1, "text_en": 1,
                        "image_en": 1, "sensor_en": 1, "text": text},
             "wires": []},
            {"id": 4, "type": "uart alarm", "index": 3, "version": "1.0.0",
             "params": {"output_format": 1, "text": text,
                        "include_big_image": False, "include_small_image": False},
             "wires": []},
            {"id": 5, "type": "local alarm", "index": 4, "version": "1.0.0",
             "params": {"sound": 1, "rgb": 1, "img": 0, "text": 0, "duration": 1},
             "wires": []},
        ],
    }


# --------------------------------------------------------------------------
# Serial console helpers
# --------------------------------------------------------------------------
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
LOG_LINE = re.compile(r"[IWE] \(\d+\) [^\r\n]*\r?\n")


class Console:
    def __init__(self, port: str, baud: int = 115200):
        self.ser = serial.Serial(port, baud, timeout=0.1)
        self.ser.reset_input_buffer()

    def read_for(self, seconds: float, until: str | None = None) -> str:
        out, end = "", time.time() + seconds
        while time.time() < end:
            chunk = self.ser.read(4096).decode(errors="replace")
            if chunk:
                out += chunk
                if until and until in out:
                    break
        return ANSI.sub("", out)

    def send(self, line: str) -> None:
        self.ser.write((line + "\r\n").encode())
        self.ser.flush()

    def cmd(self, line: str, wait: float = 2.0) -> str:
        self.send("")              # wake the prompt
        self.read_for(0.3)
        self.send(line)
        return self.read_for(wait)

    def load_flow(self, flow: dict) -> str:
        payload = json.dumps(flow, separators=(",", ":"))
        self.send("")
        self.read_for(0.3)
        # "\r" only: the console ends the line on "\r", and a trailing "\n" would be
        # read by the JSON prompt as an empty taskflow (parse fails, payload is lost).
        self.ser.write(b"taskflow -i -j\r")
        self.ser.flush()
        got = self.read_for(3, until="Please input taskflow json")
        if "Please input taskflow json" not in got:
            raise RuntimeError("Console did not ask for JSON. Wrong port? Output was:\n" + got)
        self.ser.write((payload + "\n").encode())   # firmware reads one line (max 100 KB)
        self.ser.flush()
        return self.read_for(5)

    def export_flow(self) -> dict:
        self.send("")
        self.read_for(0.3)
        self.ser.write(b"taskflow -e\r")
        self.ser.flush()
        # Voice/app tasks embed base64 MP3 audio (~60 KB), so wait for the prompt.
        raw = self.read_for(30, until="\nSenseCAP>")
        # Device log lines can land in the middle of the JSON; drop them.
        out = LOG_LINE.sub("", raw)
        if '{"tlid"' not in out:
            raise RuntimeError("No running task flow. Output was:\n" + raw)
        return json.JSONDecoder().raw_decode(out[out.index('{"tlid"'):])[0]


def add_http_alarm(flow: dict, silence: int = 5) -> dict:
    """Wire an "http alarm" block after the flow's "alarm trigger"."""
    blocks = flow["task_flow"]
    trigger = next(b for b in blocks if b["type"] == "alarm trigger")
    hid = max(b["id"] for b in blocks) + 1
    blocks.append({"id": hid, "type": "http alarm", "index": len(blocks), "version": "1.0.0",
                   "params": {"silence_duration": silence, "time_en": 1, "text_en": 1,
                              "image_en": 1, "sensor_en": 1, "text": trigger["params"]["text"]},
                   "wires": []})
    trigger["wires"][0].append(hid)
    flow["tlid"] = flow["ctd"] = int(time.time() * 1000)
    return flow


def main() -> None:
    ap = argparse.ArgumentParser(description="Control a SenseCAP Watcher over USB")
    ap.add_argument("-p", "--port", help="serial port, e.g. /dev/ttyACM0, /dev/cu.usbmodem…, COM5")
    ap.add_argument("-b", "--baud", type=int, default=115200)
    sub = ap.add_subparsers(dest="action", required=True)
    sub.add_parser("ports", help="list serial ports")
    ld = sub.add_parser("load", help="load a preset or a task-flow JSON file")
    ld.add_argument("flow", help=f"preset ({', '.join(PRESETS)}) or path to .json")
    ld.add_argument("--conf", type=int, default=65, help="confidence threshold for presets")
    ld.add_argument("--silence", type=int, default=5, help="seconds between alarms")
    ld.add_argument("--dry-run", action="store_true", help="print the JSON, don't send")
    sub.add_parser("export", help="print the running task flow")
    ah = sub.add_parser("add-http", help="add an http alarm to the running task (e.g. one made by voice) and reload it")
    ah.add_argument("--silence", type=int, default=5, help="seconds between alarms")
    sub.add_parser("battery")
    sub.add_parser("reboot")
    rgb = sub.add_parser("rgb", help="set LED colour")
    rgb.add_argument("r", type=int); rgb.add_argument("g", type=int); rgb.add_argument("b", type=int)
    rgb.add_argument("-m", "--mode", type=int, default=3)
    c = sub.add_parser("cmd", help="send any console command")
    c.add_argument("line")
    sub.add_parser("monitor", help="stream the device log (Ctrl+C to stop)")
    a = ap.parse_args()

    if a.action == "ports":
        for p in list_ports.comports():
            print(f"{p.device:30} {p.description}  [{p.hwid}]")
        return

    if a.action == "load":
        if a.flow in PRESETS:
            p = PRESETS[a.flow]
            flow = build_flow(p["model_type"], p["cls"], p["text"], a.conf, a.silence)
        else:
            with open(a.flow) as f:
                flow = json.load(f)
        if a.dry_run:
            print(json.dumps(flow, indent=2))
            return

    if not a.port:
        sys.exit("Give the serial port with -p (see: watcher/control.py ports)")
    con = Console(a.port, a.baud)

    if a.action == "load":
        print(con.load_flow(flow))
    elif a.action == "export":
        print(json.dumps(con.export_flow()))
    elif a.action == "add-http":
        flow = con.export_flow()
        if any(b["type"] == "http alarm" for b in flow["task_flow"]):
            print(f"'{flow['tn']}' already has an http alarm")
        else:
            print(con.load_flow(add_http_alarm(flow, a.silence)))
    elif a.action == "battery":
        print(con.cmd("battery"))
    elif a.action == "reboot":
        print(con.cmd("reboot", 1))
    elif a.action == "rgb":
        print(con.cmd(f"rgb -r {a.r} -g {a.g} -b {a.b} -m {a.mode}"))
    elif a.action == "cmd":
        print(con.cmd(a.line, 3))
    elif a.action == "monitor":
        try:
            while True:
                sys.stdout.write(con.read_for(0.5)); sys.stdout.flush()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
