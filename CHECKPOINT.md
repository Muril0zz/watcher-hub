# Checkpoint: 2026-10-22

## Working on real hardware
- **Voice commands → events.** Hold the Watcher's wheel, say "Move the arm up/down/left/right", release.
  `receiver.py --voice` reads the transcript from the USB console log (`vi: sst_text:`) and emits
  `{"source": "voice", "command": "arm_up", ...}`. Verified: "Move the arm up." → `arm_up`,
  "Move down the arm." → `arm_down`, "Move it to the left." → `arm_left` (`arm_right` not tried yet).
- **USB port auto-detect.** No `-p` needed: picks the `1A86:55D2` port that answers `SenseCAP>`.
  Port names change between USB sockets (`…0094923` one day, `…0110123` the next).
- **Camera alarms over HTTP.** Gesture preset and a voice-created task both reached the receiver.
  Voice-created tasks only notify the SenseCraft app; run `control.py add-http` to also push to us.
- **Task loading over USB.** Fixed: the command must end in `\r` only (see CLAUDE.md).

## Run it
```bash
cd watcher-hub && source .venv/bin/activate
python watcher/receiver.py --voice        # alarms + voice commands
python -m unittest discover -s tests -v   # no hardware needed
```
`control.py` (load / add-http / battery) needs the USB port too: stop the receiver first.

## Open items
- **Nothing moves the arm yet.** `on_event()` in `watcher/receiver.py` is empty. Need the SO-ARM101
  controller's interface (HTTP, WebSocket or Python call) from the arm owner, then forward
  `evt["command"]` there.
- **Voice listener dies silently** if the USB port drops or another process opens it: the HTTP
  server keeps running without voice. Should exit or reconnect instead.
- **The Watcher answers every command out loud** (SenseCraft chat mode). Can't be turned off from code.
- **Hold the wheel for the whole sentence.** Releasing early cuts the transcript ("move the").
- **HTTP alarm URL is set in the SenseCraft app** and must match the laptop's current LAN IP
  (`ipconfig getifaddr en0`); it was stale once (192.168.0.228 vs 172.20.10.4).
- Voice uses SenseCraft cloud speech-to-text: needs Wi-Fi with internet, adds ~5–8 s latency.
