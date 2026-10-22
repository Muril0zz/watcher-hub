"""End-to-end test against the simulated Watcher (no hardware needed).

  python3 -m unittest discover -s tests -v

Flow: start receiver -> start fake Watcher pushing to it -> load the
gesture preset through watcher/control.py -> expect an alarm event in
data/events.jsonl with the right text, EUI, sensors and a saved image.
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class EndToEnd(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.port = free_port()
        self.procs = []
        self.procs.append(subprocess.Popen(
            [PY, os.path.join(ROOT, "watcher", "receiver.py"),
             "--host", "127.0.0.1", "--port", str(self.port)],
            cwd=self.tmp, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True))
        fake = subprocess.Popen(
            [PY, "-u", os.path.join(ROOT, "tools", "fake_watcher.py"),
             "--push", f"http://127.0.0.1:{self.port}", "--every", "0.5"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        self.procs.append(fake)
        self.serial_port = fake.stdout.readline().strip().split()[-1]
        self._wait_http()

    def tearDown(self):
        for p in self.procs:
            p.terminate()
            p.wait(timeout=5)
            if p.stdout:
                p.stdout.close()

    def _wait_http(self):
        for _ in range(50):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}/", timeout=1)
                return
            except Exception:
                time.sleep(0.1)
        self.fail("receiver did not start")

    def _control(self, *args) -> str:
        r = subprocess.run([PY, os.path.join(ROOT, "watcher", "control.py"),
                            "-p", self.serial_port, *args],
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_battery(self):
        self.assertIn("battery percentage: 87%", self._control("battery"))

    def test_load_gesture_and_receive_alarm(self):
        out = self._control("load", "gesture")
        self.assertIn("import from json success", out)
        self.assertIn("Open palm", self._control("export"))

        log = os.path.join(self.tmp, "data", "events.jsonl")
        for _ in range(60):
            if os.path.exists(log) and os.path.getsize(log) > 0:
                break
            time.sleep(0.1)
        else:
            self.fail("no alarm received")
        with open(log) as f:
            evt = json.loads(f.readline())
        self.assertEqual(evt["source"], "http")
        self.assertEqual(evt["device_eui"], "2CF7F1C98280008D")
        self.assertEqual(evt["text"], "Open palm: help requested")
        self.assertEqual(evt["sensor"]["CO2"], 612)
        self.assertTrue(os.path.exists(os.path.join(self.tmp, evt["image_path"])))

    def test_add_http_to_voice_task(self):
        # Shape of a task created by voice: cloud model, MP3 audio, no http alarm.
        voice = {"tlid": 1, "ctd": 1, "tn": "Alert: Spotting Someone Nearby", "type": 3,
                 "task_flow": [
                     {"id": 10, "type": "ai camera", "index": 0, "params": {"model_type": 0}, "wires": [[20]]},
                     {"id": 20, "type": "alarm trigger", "index": 1,
                      "params": {"text": "Someone detected", "audio": "A" * 56000}, "wires": [[30]]},
                     {"id": 30, "type": "sensecraft alarm", "index": 2,
                      "params": {"silence_duration": 10, "text": "Someone detected"}, "wires": []}]}
        path = os.path.join(self.tmp, "voice.json")
        with open(path, "w") as f:
            json.dump(voice, f)
        self.assertIn("import from json success", self._control("load", path))

        self.assertIn("import from json success", self._control("add-http"))
        self.assertIn("already has an http alarm", self._control("add-http"))

        log = os.path.join(self.tmp, "data", "events.jsonl")
        for _ in range(60):
            if os.path.exists(log) and os.path.getsize(log) > 0:
                break
            time.sleep(0.1)
        else:
            self.fail("no alarm received")
        with open(log) as f:
            self.assertEqual(json.loads(f.readline())["text"], "Someone detected")


class Voice(unittest.TestCase):
    def test_voice_forwarded_to_webhook(self):
        self.check_forwarded([])

    def test_xiaozhi_voice_forwarded_to_webhook(self):
        received = self.check_forwarded(["--xiaozhi"])
        # Neither the wake-word echo (">> Alexa.") nor the reply ("<<") is forwarded.
        self.assertTrue(all(r["text"] == "Move the arm to the left." for r in received))

    def check_forwarded(self, fake_args: list) -> list:
        received = []

        class Arm(BaseHTTPRequestHandler):
            def do_POST(self):
                received.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                self.send_response(200)
                self.end_headers()

            def log_message(self, *args):
                pass

        arm = HTTPServer(("127.0.0.1", 0), Arm)
        threading.Thread(target=arm.serve_forever, daemon=True).start()
        tmp = tempfile.mkdtemp()
        fake = subprocess.Popen(
            [PY, "-u", os.path.join(ROOT, "tools", "fake_watcher.py"),
             "--say", "Move the arm to the left.", "--every", "0.5", *fake_args],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        serial_port = fake.stdout.readline().strip().split()[-1]
        receiver = subprocess.Popen(
            [PY, os.path.join(ROOT, "watcher", "receiver.py"), "--host", "127.0.0.1",
             "--port", str(free_port()), "--voice", serial_port,
             "--forward", f"http://127.0.0.1:{arm.server_port}/voice"],
            cwd=tmp, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        try:
            log = os.path.join(tmp, "data", "events.jsonl")
            for _ in range(60):
                if os.path.exists(log) and os.path.getsize(log) > 0:
                    break
                time.sleep(0.1)
            else:
                self.fail("no voice event received")
            with open(log) as f:
                evt = json.loads(f.readline())
            self.assertEqual(evt["source"], "voice")
            self.assertEqual(evt["text"], "Move the arm to the left.")
            for _ in range(30):
                if len(received) >= 2:  # the fake repeats every 0.5 s
                    break
                time.sleep(0.1)
            self.assertEqual(received[0]["source"], "voice")
            self.assertEqual(received[0]["text"], "Move the arm to the left.")
            return received
        finally:
            arm.shutdown()
            arm.server_close()
            for p in (receiver, fake):
                p.terminate()
                p.wait(timeout=5)
                p.stdout.close()


if __name__ == "__main__":
    unittest.main()
