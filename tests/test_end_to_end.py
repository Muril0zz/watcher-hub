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
import time
import unittest
import urllib.request

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
        self.assertIn("battery: 87", self._control("battery"))

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


if __name__ == "__main__":
    unittest.main()
