# Checkpoint: 2026-10-22

## XiaoZhi firmware (branch `xiaozhi`) — current state of the device
The Watcher now runs open-source **XiaoZhi** (`78/xiaozhi-esp32` v2.5.2, ESP-IDF v6.1) instead of
SenseCraft. Details, build and restore steps: CLAUDE.md → "XiaoZhi firmware".

Verified on hardware:
- Boots without panic; joins Wi-Fi (hotspot `Xiaozhi-5AFD` provisioning); activated on xiaozhi.me.
- **Wake word "Marco"** (custom, MultiNet7 English) triggers a conversation; no wheel needed.
  First tested with "Alexa" (WakeNet) at 0.32 s wake → listening, 1.25 s wake → first reply text.
- **Voice → ntfy.** `receiver.py --voice <port> --forward https://ntfy.sh/$WATCHER_TOPIC` forwards
  each XiaoZhi transcript as `{"source": "voice", "text", "received_at"}`; the wake-word echo and the
  device's own replies are not forwarded. Read back from ntfy: "Yeah, I want you to move the arm up."
- nvsfactory (0x9000) verified unchanged after every flash; full backup in `data/firmware-backup/`.

Not working / open:
- **Replies are in Chinese**: set the agent's language and voice to English on xiaozhi.me →
  Console → Configure role. The "What time is it?" test with an English answer is still to do.
- **Keeps listening after each reply**, so room conversation is transcribed and forwarded until it
  goes idle. Click the wheel to end, or the arm must ignore text that isn't a command.
- Start speaking ~0.5 s after the wake word, or the first word is cut ("The arm up.").
- SenseCraft-only features below (task flows, HTTP/UART alarms, push-to-talk, `control.py`) don't
  work on XiaoZhi. Restore the full backup to get them back.

## SenseCraft firmware (before XiaoZhi)

## Working on real hardware
- **Voice commands → events.** Hold the Watcher's wheel, say "Move the arm up/down/left/right", release.
  `receiver.py --voice` reads the transcript from the USB console log (`vi: sst_text:`) and emits
  `{"source": "voice", "text": "Move the arm up.", ...}` for every transcript (no parsing here).
- **Voice → webhook.** `--forward URL` (repeatable) POSTs `{"source": "voice", "text", "received_at"}`
  to the arm side, which interprets the text. 2 s timeout; failures are logged, not retried.
- **Hosted relay: ntfy.sh.** Laptop and arm are on different networks, so we forward to a secret
  ntfy topic and the arm subscribes (the arm can't receive a push from outside its NAT). Verified
  with the fake Watcher → ntfy.sh → read back; not yet with the real arm. The topic name is the only
  secret: share it privately, never commit it (repo is public). Messages are cached ~12 h.

  Arm side (subscribe, our JSON is in `message`):
  ```python
  import json, urllib.request
  for line in urllib.request.urlopen("https://ntfy.sh/<TOPIC>/json"):
      evt = json.loads(line)
      if evt["event"] == "message":
          text = json.loads(evt["message"])["text"]   # interpret and move the arm
  ```
- **USB port auto-detect.** No `-p` needed: picks the `1A86:55D2` port that answers `SenseCAP>`.
  Port names change between USB sockets (`…0094923` one day, `…0110123` the next).
- **Camera alarms over HTTP.** Gesture preset and a voice-created task both reached the receiver.
  Voice-created tasks only notify the SenseCraft app; run `control.py add-http` to also push to us.
- **Task loading over USB.** Fixed: the command must end in `\r` only (see CLAUDE.md).

## Run it
```bash
cd watcher-hub && source .venv/bin/activate
python watcher/receiver.py --voice --forward https://ntfy.sh/$WATCHER_TOPIC
python -m unittest discover -s tests -v   # no hardware needed
```
`control.py` (load / add-http / battery) needs the USB port too: stop the receiver first.

## Open items
- **Arm side must subscribe.** Give the arm owner the topic name and the snippet above, then
  test end to end with the real Watcher and arm.
- **Voice listener dies silently** if the USB port drops or another process opens it: the HTTP
  server keeps running without voice. Should exit or reconnect instead.
- **The Watcher answers every command out loud** (SenseCraft chat mode). Can't be turned off from code.
- **Hold the wheel for the whole sentence.** Releasing early cuts the transcript ("move the").
- **HTTP alarm URL is set in the SenseCraft app** and must match the laptop's current LAN IP
  (`ipconfig getifaddr en0`); it was stale once (192.168.0.228 vs 172.20.10.4).
- Voice uses SenseCraft cloud speech-to-text: needs Wi-Fi with internet, adds ~5–8 s latency.
