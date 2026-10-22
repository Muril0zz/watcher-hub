"""
Watcher -> SO-101 arm bridge.

The arm panel (arm/panel.py, http://127.0.0.1:8101) owns the arm and its command
interpreter: everyday Spanish/English phrases, stop words, saved places, "bring me
the cup" with the wrist camera, motor protection. This bridge only relays what the
Watcher heard or saw:

  voice transcript (push-to-talk)  -> POST /api/command {"text": ..., "source": "watcher-voice"}
  open-palm gesture alarm          -> POST /api/command {"event": "help_gesture", "source": "watcher"}

Safety: HTTP alarms come over Wi-Fi, so only the configured device EUI is accepted
(when set), and commands are rate-limited. Stop words are never rate-limited.
"""
import json
import re
import sys
import time
import urllib.error
import urllib.request

DEFAULT_PANEL_URL = "http://127.0.0.1:8101/api/command"
MIN_INTERVAL_S = 1.5  # at most one forwarded command per this many seconds
STOP_WORDS = re.compile(r"\b(stop|halt|freeze|para|pará|basta|alto|quieto)\b", re.IGNORECASE)
HELP_GESTURE = re.compile(r"\b(palm|help|paper)\b", re.IGNORECASE)


class ArmBridge:
    def __init__(self, panel_url: str = DEFAULT_PANEL_URL, allowed_eui: str | None = None):
        self.panel_url = panel_url
        self.allowed_eui = allowed_eui.upper() if allowed_eui else None
        self.last_sent = 0.0

    def handle(self, evt: dict) -> None:
        source = evt.get("source")
        if source == "voice":
            text = (evt.get("text") or "").strip()
            if text:
                self._send({"text": text, "source": "watcher-voice"}, urgent=bool(STOP_WORDS.search(text)))
            return
        # http / uart alarms from a running task
        eui = (evt.get("device_eui") or "").upper()
        if source == "http" and self.allowed_eui and eui != self.allowed_eui:
            print(f"arm bridge: ignored alarm from unknown device {eui or '?'}", file=sys.stderr)
            return
        if HELP_GESTURE.search(evt.get("text") or ""):
            self._send({"event": "help_gesture", "source": "watcher"})

    def _send(self, body: dict, urgent: bool = False) -> None:
        now = time.monotonic()
        if not urgent and now - self.last_sent < MIN_INTERVAL_S:
            print(f"arm bridge: rate-limited {body}", file=sys.stderr)
            return
        self.last_sent = now
        req = urllib.request.Request(
            self.panel_url, data=json.dumps(body).encode(), method="POST",
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=2) as resp:
                print(f"arm bridge -> panel {resp.status}: {body}", flush=True)
        except (urllib.error.URLError, OSError) as e:
            print(f"arm bridge: panel unreachable ({e}); is arm/panel.py running?", file=sys.stderr)
