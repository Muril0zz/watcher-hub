# watcher-hub

Control a SenseCAP Watcher from a laptop (USB-C console) and receive its alarms (HTTP push), as the Watcher side of our elderly-assistance hackathon project (Watcher + Rokid glasses + SO-ARM101).

## Quick start
```bash
./setup.sh                      # venv, deps, tests, serial ports, LAN IP
source .venv/bin/activate
```
1. SenseCraft app → device Settings → **HTTP Message Block** → URL `http://<LAN-IP>:8887`.
2. Terminal 1: `python watcher/receiver.py`
3. Terminal 2: plug the Watcher in by USB-C, then
   `python watcher/control.py battery` → `python watcher/control.py load gesture` (the console port is auto-detected; add `-p PORT` to override)
4. Show an open palm to the Watcher → the alarm appears in terminal 1 and `data/events.jsonl`.

No hardware: `python tools/fake_watcher.py --push http://127.0.0.1:8887` and use the port it prints.

## SO-ARM101 arm
[`arm/`](arm/README.md) is the arm side: a local web panel (voice in Spanish/English, big-button mode for older
users, saved places, "bring me the cup" with the wrist camera, motor protection). To let the Watcher drive it:

```bash
cd arm && .venv/bin/python panel.py                                   # terminal A, then open http://127.0.0.1:8101 in Chrome
python watcher/receiver.py --voice --arm --token <secret> --eui <EUI>  # terminal B
```

Push-to-talk on the Watcher ("bring me the cup", "turn left", "stop") and the open-palm gesture now reach the arm.

## With Claude Code
Open this folder and run `claude`. `CLAUDE.md` holds the full context. A good first prompt:

> Run ./setup.sh and fix anything that fails on this machine. Then, with the Watcher plugged in by USB-C, find the console port, run `battery`, load the gesture preset and confirm a real alarm reaches the receiver. Update tools/fake_watcher.py if the real console output differs, and keep the tests green.

Then, for integration:

> Turn on_event() in watcher/receiver.py into a small event bus (WebSocket on port 8765) so the arm controller and the Rokid glasses app can subscribe to Watcher alarms. Add a test using the fake Watcher.
