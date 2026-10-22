#!/usr/bin/env python3
"""
SenseCAP Watcher -> computer receiver.

Two modes, matching the two local output channels in the Watcher firmware:

  http  (default)  Run a tiny HTTP server. In the SenseCraft app, enable
                   "HTTP Push Notification" on the task and set
                   HTTP URL = http://<this-computer-LAN-IP>:<port>
                   HTTP Token = anything (optional; checked if --token is set)
                   The Watcher POSTs JSON to <URL>/v1/notification/event.

  uart             Read the Watcher's Grove/UART port (115200 8N1) through a
                   USB-serial adapter. Enable "Serial Port / UART Output" on
                   the task. Each alarm arrives as one JSON line ending \\r\\n.

  --voice [PORT]   Also read the Watcher's USB-C console and turn every
                   push-to-talk transcript into a voice event. Uses the
                   Watcher's SenseCraft speech-to-text; PORT is auto-detected
                   if omitted. control.py can't use that port while this runs.
                   Also reads XiaoZhi firmware transcripts (after the wake
                   word); give PORT explicitly there, since auto-detect looks
                   for the SenseCraft prompt.

  --forward URL    POST each voice transcript to URL as JSON
                   {"source": "voice", "text", "received_at"}. Repeatable.
                   The receiver (e.g. the arm controller) interprets the text.

Every event is printed, appended to data/events.jsonl, its image saved to
data/images/, and passed to on_event() -- put your own logic there
(forward to the arm / glasses, MQTT, websocket, etc.).

Usage:
  python3 watcher/receiver.py                    # HTTP on 0.0.0.0:8887
  python3 watcher/receiver.py --port 9000 --token secret
  python3 watcher/receiver.py --voice                         # + voice commands
  python3 watcher/receiver.py --voice --forward http://arm-host:5000/voice
  python3 watcher/receiver.py --mode uart --serial /dev/ttyUSB0   # pip install pyserial
"""
import argparse
import base64
import json
import os
import re
import sys
import threading
import time
import urllib.request
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

IMG_DIR = os.path.join("data", "images")
LOG_FILE = os.path.join("data", "events.jsonl")
FORWARD_URLS: list[str] = []


# --------------------------------------------------------------------------
# Your integration hook
# --------------------------------------------------------------------------
def on_event(evt: dict) -> None:
    """Called once per Watcher alarm with a normalized event dict:
    {
      "source": "http" | "uart" | "voice",
      "received_at": ISO time on this computer,
      "device_eui": str | None,
      "timestamp_ms": int | None,        # device clock (HTTP only)
      "text": str,                       # task prompt / alarm message / voice transcript
      "image_path": str | None,          # saved JPEG
      "sensor": {"temperature", "humidity", "CO2"} | {},   # HTTP only
      "inference": {...} | {},           # boxes/classes if present
      "raw": original payload without the base64 image
    }
    """
    if evt["source"] != "voice":
        return
    body = json.dumps({k: evt[k] for k in ("source", "text", "received_at")}).encode()
    for url in FORWARD_URLS:
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req, timeout=2).close()
        except Exception as e:  # one dead listener must not block the others
            print(f"forward to {url} failed: {e}", file=sys.stderr)


# --------------------------------------------------------------------------
# Shared helpers
# --------------------------------------------------------------------------
def save_image(b64: str, prefix: str) -> str | None:
    if not b64:
        return None
    if b64.startswith("data:"):  # tolerate a data-URI prefix
        b64 = b64.split(",", 1)[-1]
    try:
        data = base64.b64decode(b64)
    except Exception:
        return None
    os.makedirs(IMG_DIR, exist_ok=True)
    path = os.path.join(IMG_DIR, f"{prefix}_{datetime.now():%Y%m%d_%H%M%S_%f}.jpg")
    with open(path, "wb") as f:
        f.write(data)
    return path


def emit(evt: dict) -> None:
    sensor = evt.get("sensor") or {}
    sensor_str = " ".join(f"{k}={v}" for k, v in sensor.items())
    print(f"[{evt['received_at']}] {evt['source'].upper()} "
          f"eui={evt.get('device_eui')} text={evt.get('text')!r} "
          f"{sensor_str} img={evt.get('image_path')}", flush=True)
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(evt) + "\n")
    try:
        on_event(evt)
    except Exception as e:  # never let user code kill the receiver
        print(f"on_event error: {e}", file=sys.stderr)


# --------------------------------------------------------------------------
# HTTP mode  (firmware: tf_module_http_alarm.c)
# Body: {"requestId","deviceEui","events":{"timestamp","text","img",
#        "data":{"sensor":{"temperature","humidity","CO2"},"inference":{...}}}}
# Headers: Authorization: <token>, API-OBITER-DEVICE-EUI: <eui>
# Expected reply: JSON with "code": 200
# --------------------------------------------------------------------------
def make_handler(token: str | None):
    class Handler(BaseHTTPRequestHandler):
        def _reply(self, status: int, body: dict):
            payload = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):  # handy health check from a browser
            self._reply(200, {"code": 200, "msg": "watcher receiver up"})

        def do_POST(self):
            if token and self.headers.get("Authorization", "") not in (token, f"Device {token}"):
                return self._reply(401, {"code": 401, "msg": "bad token"})
            length = int(self.headers.get("Content-Length", 0))
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                return self._reply(400, {"code": 400, "msg": "invalid json"})

            events = body.get("events") or {}
            data = events.get("data") or {}
            img_b64 = events.pop("img", "")
            evt = {
                "source": "http",
                "path": self.path,
                "received_at": datetime.now().isoformat(timespec="seconds"),
                "device_eui": body.get("deviceEui") or self.headers.get("API-OBITER-DEVICE-EUI"),
                "timestamp_ms": events.get("timestamp"),
                "text": events.get("text", ""),
                "image_path": save_image(img_b64, "http"),
                "sensor": data.get("sensor") or {},
                "inference": data.get("inference") or {},
                "raw": body,
            }
            emit(evt)
            self._reply(200, {"code": 200, "msg": "ok"})

        def log_message(self, fmt, *args):  # keep the console clean
            pass

    return Handler


def run_http(host: str, port: int, token: str | None) -> None:
    srv = ThreadingHTTPServer((host, port), make_handler(token))
    print(f"Listening on http://{host}:{port}  (Watcher posts to /v1/notification/event)")
    print("Set the Watcher's HTTP URL to http://<this-computer-LAN-IP>:%d" % port)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


# --------------------------------------------------------------------------
# UART mode  (firmware: tf_module_uart_alarm.c, UART2 TX=GPIO19 RX=GPIO20)
# JSON line: {"prompt","big_image","small_image","inference":{...}}
# --------------------------------------------------------------------------
def run_uart(port: str, baud: int) -> None:
    try:
        import serial  # pyserial
    except ImportError:
        sys.exit("UART mode needs pyserial:  pip install pyserial")
    ser = serial.Serial(port, baud, timeout=1)
    print(f"Reading {port} @ {baud} 8N1")
    buf = b""
    while True:
        chunk = ser.read(ser.in_waiting or 1)
        if not chunk:
            continue
        buf += chunk
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            line = line.strip()
            if not line.startswith(b"{"):
                continue  # binary-format packets / noise are skipped
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            big = msg.pop("big_image", "")
            small = msg.pop("small_image", "")
            emit({
                "source": "uart",
                "received_at": datetime.now().isoformat(timespec="seconds"),
                "device_eui": None,
                "timestamp_ms": int(time.time() * 1000),
                "text": msg.get("prompt", ""),
                "image_path": save_image(small or big, "uart"),
                "sensor": {},
                "inference": msg.get("inference") or {},
                "raw": msg,
            })


# --------------------------------------------------------------------------
# Voice mode  (firmware log over the USB-C console, 115200)
# After push-to-talk the firmware logs "I (...) vi: sst_text: <transcript>".
# XiaoZhi logs "I (...) Application: >> <transcript>" (its replies are "<<").
# It also sends the wake-word audio to the server, so the first transcript after
# "Wake word detected: Alexa" is just "Alexa"; that one is dropped.
# --------------------------------------------------------------------------
SST = re.compile(r"vi: sst_text: ?(?P<sst_text>.*)|Application: >> (?P<xiaozhi>.*)"
                 r"|Wake word detected: (?P<wake>[^(]+)")


def run_voice(port: str, baud: int) -> None:
    import serial  # pyserial
    ser = serial.Serial(port, baud, timeout=1)
    print(f"Listening for voice input on {port} (SenseCraft: hold the wheel; XiaoZhi: wake word)")
    buf = b""
    wake = None
    while True:
        buf += ser.read(ser.in_waiting or 1)
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            m = SST.search(re.sub(r"\x1b\[[0-9;]*m", "", line.decode(errors="replace")))
            if not m:
                continue
            text = m.group(m.lastgroup).strip()
            if m.lastgroup == "wake":
                wake = re.sub(r"\W", "", text).casefold()
                continue
            if m.lastgroup == "xiaozhi" and wake is not None:
                said, expected, wake = re.sub(r"\W", "", text).casefold(), wake, None
                if said == expected:
                    continue
            if not text:
                continue
            emit({
                "source": "voice",
                "received_at": datetime.now().isoformat(timespec="seconds"),
                "device_eui": None,
                "timestamp_ms": int(time.time() * 1000),
                "text": text,
                "image_path": None,
                "sensor": {},
                "inference": {},
                "raw": {m.lastgroup: text},
            })


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Receive SenseCAP Watcher alarms")
    ap.add_argument("--mode", choices=["http", "uart"], default="http")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8887)
    ap.add_argument("--token", default=None, help="require this HTTP Token (optional)")
    ap.add_argument("--serial", default="/dev/ttyUSB0", help="serial device for uart mode")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--voice", metavar="PORT", nargs="?", const="auto",
                    help="voice commands from the Watcher's USB-C console (port auto-detected if omitted)")
    ap.add_argument("--forward", metavar="URL", action="append", default=[],
                    help="POST each voice transcript to URL (repeatable)")
    a = ap.parse_args()
    FORWARD_URLS.extend(a.forward)
    if a.voice == "auto":
        from control import find_console  # watcher/ is on sys.path when run as a script
        a.voice = find_console(a.baud)
    if a.voice:
        threading.Thread(target=run_voice, args=(a.voice, a.baud), daemon=True).start()
    if a.mode == "http":
        run_http(a.host, a.port, a.token)
    else:
        run_uart(a.serial, a.baud)
