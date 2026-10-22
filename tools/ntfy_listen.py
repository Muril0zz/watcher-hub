#!/usr/bin/env python3
"""
Subscribe to the ntfy topic that receiver.py --forward publishes to and
print each voice transcript. Same code path the arm side would use.

Usage:
  python tools/ntfy_listen.py TOPIC          # or set WATCHER_TOPIC
  python tools/ntfy_listen.py TOPIC --since 10m   # also replay cached messages
"""
import argparse
import json
import os
import sys
import urllib.request

ap = argparse.ArgumentParser(description="Print voice transcripts from an ntfy topic")
ap.add_argument("topic", nargs="?", default=os.environ.get("WATCHER_TOPIC"))
ap.add_argument("--server", default="https://ntfy.sh")
ap.add_argument("--since", help="replay cached messages, e.g. 10m, 1h, all")
a = ap.parse_args()
if not a.topic:
    sys.exit("give a topic or set WATCHER_TOPIC")

url = f"{a.server}/{a.topic}/json" + (f"?since={a.since}" if a.since else "")
print(f"Subscribed to {a.server}/{a.topic} (Ctrl-C to stop)", flush=True)
try:
    for line in urllib.request.urlopen(url):
        evt = json.loads(line)
        if evt["event"] != "message":
            continue  # "open" and "keepalive" events
        try:
            body = json.loads(evt["message"])
        except json.JSONDecodeError:
            print(f"(not from receiver) {evt['message']!r}", flush=True)
            continue
        print(f"[{body.get('received_at')}] {body.get('source')}: {body.get('text')!r}", flush=True)
except KeyboardInterrupt:
    pass
