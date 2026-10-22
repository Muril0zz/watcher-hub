"""Watcher -> SO-101 arm bridge, against the simulated Watcher and a stub arm panel.

  python3 -m unittest discover -s tests -v
"""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
sys.path.insert(0, os.path.join(ROOT, "watcher"))
from arm_bridge import ArmBridge  # noqa: E402
from receiver import parse_command  # noqa: E402
from test_end_to_end import free_port  # noqa: E402


class StubPanel:
    """Stands in for arm/panel.py: records every POST /api/command body."""

    def __init__(self):
        self.received = []
        received = self.received

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                received.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                self.send_response(200)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"{}")

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/api/command"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class VoiceToArm(unittest.TestCase):
    def test_any_transcript_reaches_the_arm_panel(self):
        # Not one of the four arm_* directions: the panel's interpreter handles it, so it must get through.
        panel = StubPanel()
        fake = subprocess.Popen(
            [PY, "-u", os.path.join(ROOT, "tools", "fake_watcher.py"), "--say", "Bring me the cup please.", "--every", "0.5"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        serial_port = fake.stdout.readline().strip().split()[-1]
        receiver = subprocess.Popen(
            [PY, os.path.join(ROOT, "watcher", "receiver.py"), "--host", "127.0.0.1", "--port", str(free_port()),
             "--voice", serial_port, "--arm", panel.url, "--token", "secret"],
            cwd=tempfile.mkdtemp(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        try:
            for _ in range(60):
                if panel.received:
                    break
                time.sleep(0.1)
            else:
                self.fail("the arm panel received nothing")
            self.assertEqual(panel.received[0], {"text": "Bring me the cup please.", "source": "watcher-voice"})
        finally:
            for p in (receiver, fake):
                p.terminate()
                p.wait(timeout=5)
                p.stdout.close()
            panel.close()

    def test_arm_requires_a_token(self):
        # Without a token anyone on the Wi-Fi could post alarms that move the arm.
        result = subprocess.run([PY, os.path.join(ROOT, "watcher", "receiver.py"), "--arm"],
                                capture_output=True, text=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--token", result.stderr)


class Bridge(unittest.TestCase):
    def setUp(self):
        self.panel = StubPanel()

    def tearDown(self):
        self.panel.close()

    def test_open_palm_from_the_known_watcher_asks_for_help(self):
        ArmBridge(self.panel.url, allowed_eui="2CF7F1C98280008D").handle(
            {"source": "http", "device_eui": "2cf7f1c98280008d", "text": "Open palm: help requested"})
        self.assertEqual(self.panel.received, [{"event": "help_gesture", "source": "watcher"}])

    def test_alarms_from_another_device_are_ignored(self):
        ArmBridge(self.panel.url, allowed_eui="2CF7F1C98280008D").handle(
            {"source": "http", "device_eui": "DEADBEEF00000000", "text": "Open palm: help requested"})
        self.assertEqual(self.panel.received, [])

    def test_commands_are_rate_limited_but_stop_never_is(self):
        bridge = ArmBridge(self.panel.url)
        for text in ("turn left", "turn right", "stop"):
            bridge.handle({"source": "voice", "text": text})
        self.assertEqual([r["text"] for r in self.panel.received], ["turn left", "stop"])


class ParseCommand(unittest.TestCase):
    def test_whole_words_only(self):
        self.assertEqual(parse_command("Move the arm to the left."), "arm_left")
        self.assertIsNone(parse_command("Set an alarm for the left door"))  # "alarm" contains "arm"
        self.assertIsNone(parse_command("The farm is up north"))


if __name__ == "__main__":
    unittest.main()
