#!/usr/bin/env python3
"""
Simulated SenseCAP Watcher, for developing without the hardware (macOS/Linux).

  python3 tools/fake_watcher.py                       # console only
  python3 tools/fake_watcher.py --push http://127.0.0.1:8887

Opens a virtual serial port that mimics the `SenseCAP>` console
(taskflow -i -j / -e, battery, rgb, reboot) and prints its path, e.g.
/dev/ttys004 -> use it as `-p` for watcher/control.py.

With --push, every loaded task flow that contains an "http alarm" block
makes the fake device POST a fake alarm (same JSON as the real firmware)
to <url>/v1/notification/event every --every seconds.

With --say "move the arm up", the console also logs that push-to-talk
transcript every --every seconds (for receiver.py --voice).
"""
import argparse
import base64
import json
import os
import pty
import threading
import time
import urllib.request
import uuid

EUI = "2CF7F1C98280008D"
# 1x1 white JPEG, stands in for the 240x240 frame
TINY_JPEG = base64.b64encode(bytes.fromhex(
    "ffd8ffe000104a46494600010100000100010000ffdb004300080606070605080707070909080a0c"
    "140d0c0b0b0c1912130f141d1a1f1e1d1a1c1c20242e2720222c231c1c2837292c30313434341f27"
    "393d38323c2e333432ffc0000b080001000101011100ffc4001f00000105010101010101000000000000"
    "0000000102030405060708090a0bffc400b5100002010303020403050504040000017d01020300041105"
    "122131410613516107227114328191a1082342b1c11552d1f02433627282090a161718191a25262728"
    "292a3435363738393a434445464748494a535455565758595a636465666768696a737475767778797a"
    "838485868788898a92939495969798999aa2a3a4a5a6a7a8a9aab2b3b4b5b6b7b8b9bac2c3c4c5c6c7"
    "c8c9cad2d3d4d5d6d7d8d9dae1e2e3e4e5e6e7e8e9eaf1f2f3f4f5f6f7f8f9faffda0008010100003f00"
    "fbd3ffd9")).decode()

state = {"flow": None}


def alarm_text(flow: dict) -> str | None:
    blocks = flow.get("task_flow", [])
    if not any(b.get("type") == "http alarm" for b in blocks):
        return None
    for b in blocks:
        if b.get("type") == "alarm trigger":
            return b.get("params", {}).get("text", "alarm")
    return flow.get("tn", "alarm")


def pusher(url: str, every: float) -> None:
    while True:
        time.sleep(every)
        flow = state["flow"]
        text = alarm_text(flow) if flow else None
        if not text:
            continue
        body = {"requestId": str(uuid.uuid4()), "deviceEui": EUI,
                "events": {"timestamp": int(time.time() * 1000), "text": text,
                           "img": TINY_JPEG,
                           "data": {"sensor": {"temperature": 24.6, "humidity": 58, "CO2": 612}}}}
        req = urllib.request.Request(
            url.rstrip("/") + "/v1/notification/event", data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json", "API-OBITER-DEVICE-EUI": EUI})
        try:
            urllib.request.urlopen(req, timeout=5).read()
        except Exception as e:
            print(f"[fake] push failed: {e}", flush=True)


def console(master: int) -> None:
    buf, want_json = b"", False

    def out(s: str) -> None:
        os.write(master, s.encode())

    while True:
        buf += os.read(master, 65536)
        # Like the real console, "\r" and "\n" each end a line, so "cmd\r\n" leaves
        # an empty line behind that the JSON prompt consumes as the taskflow.
        while b"\r" in buf or b"\n" in buf:
            cut = min(i for i in (buf.find(b"\r"), buf.find(b"\n")) if i >= 0)
            raw, buf = buf[:cut], buf[cut + 1:]
            line = raw.decode(errors="replace")
            if want_json:
                want_json = False
                try:
                    state["flow"] = json.loads(line)
                    out(line + "\r\nI (1) app_cmd: taskflow import from json success!\r\nSenseCAP> ")
                    print(f"[fake] task flow loaded: {state['flow'].get('tn')}", flush=True)
                except json.JSONDecodeError:
                    out("E (1) taskflow: Failed to parse cJSON\r\nSenseCAP> ")
                continue
            if line == "taskflow -i -j":
                out("Please input taskflow json:\r\n")
                want_json = True
            elif line == "taskflow -e":
                if state["flow"]:
                    out("I (1) app_cmd: taskflow:\r\n" + json.dumps(state["flow"]) + "\r\nSenseCAP> ")
                else:
                    out("E (1) app_cmd: taskflow is not running, export fail!\r\nSenseCAP> ")
            elif line == "battery":
                out("I (1) BSP: voltage: 4169mV\r\nI (1) BSP: percentage: 87%\r\nbattery percentage: 87%\r\nSenseCAP> ")
            elif line.startswith("rgb"):
                out("SenseCAP> ")
                print(f"[fake] {line}", flush=True)
            elif line == "reboot":
                state["flow"] = None
                out("Rebooting...\r\n")
            else:
                out("SenseCAP> ")


def speaker(master: int, text: str, every: float) -> None:
    # Same shape as the real push-to-talk log line (green ANSI colour included).
    while True:
        time.sleep(every)
        os.write(master, f"\x1b[0;32mI (1) vi: sst_text: {text}\x1b[0m\r\n".encode())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--push", help="receiver base URL, e.g. http://127.0.0.1:8887")
    ap.add_argument("--every", type=float, default=5.0)
    ap.add_argument("--say", help="log this push-to-talk transcript every --every seconds")
    a = ap.parse_args()
    master, slave = pty.openpty()
    print(f"Fake Watcher console on {os.ttyname(slave)}", flush=True)
    if a.push:
        threading.Thread(target=pusher, args=(a.push, a.every), daemon=True).start()
        print(f"Pushing alarms to {a.push} every {a.every}s once an http-alarm flow is loaded", flush=True)
    if a.say:
        threading.Thread(target=speaker, args=(master, a.say, a.every), daemon=True).start()
    try:
        console(master)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
