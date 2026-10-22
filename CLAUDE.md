# watcher-hub — project context for Claude Code

Hackathon project (team of 3): connect a **SenseCAP Watcher**, **Rokid glasses** and a **SO-ARM101** arm to help elderly people in daily life. Specific use case not chosen yet. This repo is the Watcher side: a laptop controls the Watcher and receives its alarms, then forwards them to the other devices.

Approach decided: **code-first**. Control the Watcher over its USB-C serial console; receive alarms by HTTP push over Wi-Fi. No SenseCraft cloud API is used from code, but the SenseCraft cloud is allowed on the device side: tasks can be created by voice (hold the wheel button and describe what to watch for).

## Layout
- `watcher/control.py` — USB-C console client: load task flows (`load <preset|file.json>`), `export`, `battery`, `rgb`, `reboot`, `cmd`, `monitor`, `ports`. `build_flow()` makes preset flows.
- `watcher/receiver.py` — HTTP server (default `0.0.0.0:8887`) for the Watcher's alarm POSTs; also `--mode uart` for the Grove port. Writes `data/events.jsonl` and `data/images/`. **Integration hook: `on_event(evt)`** — POSTs each voice transcript to the `--forward` URLs (webhook to the arm, which interprets the text). `--voice` reads both SenseCraft and XiaoZhi transcripts from the console log.
- `data/firmware-backup/` (gitignored, **private**: contains device keys) — full flash dump, nvsfactory, restore commands, XiaoZhi build configs.
- `flows/*.json` — preset task flows (person, gesture, pet).
- `tools/fake_watcher.py` — simulated Watcher (virtual serial console + fake HTTP pushes). Use it whenever the hardware is not plugged in. `--say TEXT --xiaozhi` logs transcripts in the XiaoZhi format.
- `tools/ntfy_listen.py` — subscribes to the ntfy topic and prints voice transcripts (what the arm side sees).
- `tests/test_end_to_end.py` — receiver + fake Watcher + control, no hardware.
- `docs/taskflow-blocks-reference.md` — official parameters of every task-flow block.

## Commands
```bash
./setup.sh                                   # venv + deps + tests + ports + LAN IP
source .venv/bin/activate
python -m unittest discover -s tests -v      # run after every change
python watcher/receiver.py                   # receive alarms
python watcher/control.py ports
python watcher/receiver.py --voice           # alarms + push-to-talk voice commands
python watcher/receiver.py --voice --forward https://ntfy.sh/$WATCHER_TOPIC   # hosted relay to the arm (topic is secret, never commit it)
python watcher/receiver.py --voice /dev/cu.usbmodem…123 --forward https://ntfy.sh/$WATCHER_TOPIC   # XiaoZhi: port must be given
python watcher/control.py battery            # console port auto-detected (-p PORT to override)
python watcher/control.py load gesture
python tools/ntfy_listen.py $WATCHER_TOPIC     # check the relay from any network
python tools/fake_watcher.py --push http://127.0.0.1:8887   # no hardware
```

## The device
- Unit name "Marco", EUI `2CF7F1C98280008C` (from `factory_info`; was written `…8D` before), ESP32-S3 MAC `44:b1:76:b0:5a:fc`, 32 MB flash.
- **Now runs XiaoZhi firmware** on branch `xiaozhi` (see "XiaoZhi firmware" below). Everything else in this section and in "Protocol facts" describes the factory SenseCraft firmware, which a full backup can restore. Under SenseCraft: Remote Control ON (a task sent from the app replaces one loaded over USB).
- App setting **HTTP Message Block** must be `http://<laptop-LAN-IP>:8887`. Laptop and Watcher on the same Wi-Fi; allow incoming 8887 in the firewall.
- USB-C usually enumerates **two** serial ports (ESP32 + Himax AI chip). The `SenseCAP>` console is on the ESP32 one, 115200 baud. `find_console()` picks it automatically (VID:PID 1A86:55D2, answers `SenseCAP>`); port names change between USB sockets.

## Protocol facts (verified in firmware source, Seeed-Studio/SenseCAP-Watcher-Firmware `examples/factory_firmware`)
- **Alarms are push-only**: the Watcher sends something only when a running task fires. There is no status polling API.
- HTTP push: `POST <URL>/v1/notification/event`, JSON `{"requestId","deviceEui","events":{"timestamp"(ms),"text","img"(base64 JPEG 240x240),"data":{"sensor":{"temperature","humidity","CO2"},"inference":{...}}}}`. Headers `Authorization: <token>`, `API-OBITER-DEVICE-EUI`. Reply `{"code":200}`. (`task_flow_module/tf_module_http_alarm.c`)
- UART (Grove port): 115200 8N1, one JSON line per alarm `{"prompt","big_image","small_image","inference"}` ending `\r\n`. (`tf_module_uart_alarm.c`)
- Console (`main/app/app_cmd.c`): `taskflow -i -j` prints `Please input taskflow json:` then reads ONE line of JSON (max 100 KB). Send the command with `\r` only (verified on hardware): the console ends lines on `\r` or `\n`, so a `\r\n` leaves an empty line that is imported as the taskflow and the real JSON then hits the normal prompt (1024-byte line limit, `Unrecognized command`); `taskflow -e` exports; `battery`, `rgb -r -g -b -m`, `reboot`, `record`, `vi_ctrl`, `wifi_sta`, `factory_info`, `help`.
- BLE alternative (what the app uses, `main/app/at_cmd.c`, `app_ble.c`): service `49535343-FE7D-4AE5-8FA9-9FAFD205E455`, write `49535343-8841-43F4-A8D4-ECBE34729BB3`, notify `49535343-1E4D-4BD9-BA61-23C647249616`; frames `AT+taskflow={json}\r\n`, `AT+devicecfg=`, `AT+localservice=` (sets HTTP push URL), `AT+emoji=`. Not implemented yet.
- Task flow = JSON graph of blocks: `ai camera` | `timer` → `alarm trigger` | `image analyzer` → `http alarm` | `uart alarm` | `local alarm` | `sensecraft alarm`. `tlid`/`ctd` = unique ids (use a timestamp).
- Built-in Himax models (`ai camera.params.model_type`): 1 person (`person`), 2 pet (`dog`,`cat`), 3 gesture (`paper` = open palm). 0 = cloud model by URL. Condition `{"class":X,"mode":1,"type":2,"num":0}` means "count of X > 0".
- `http alarm` URL/token are NOT in the flow; they come from the app's HTTP Message Block setting.

## XiaoZhi firmware (installed 2026-10-22, replaces SenseCraft)
- Repo `github.com/78/xiaozhi-esp32` tag `v2.5.2` (commit `49b4380b3faa0ceadd28a3e78aaf0f311c46c57e`), checkout at `~/src/xiaozhi-esp32` (outside this repo). Upstream, not Seeed's fork `Wvirgil123/xiaozhi-esp32`, which is a stale copy of it. Board `sensecap-watcher`.
- **ESP-IDF v6.1** at `~/esp/esp-idf` (`. ~/esp/esp-idf/export.sh`); v2.4.0+ needs IDF ≥ 6.0.1 (Seeed's wiki still says 5.5.1). esptool 5.6.0.
- **Wake word "Marco"**: custom wake word on ESP-SR MultiNet7 English (`mn7_en`), threshold 20 %, detected on the device. Speech-to-text, LLM and TTS run on the server. Wake word only works from idle, not while listening. Before "Marco" the build used WakeNet `wn9_alexa` (config in `~/src/xiaozhi-esp32/sdkconfig.alexa.bak`).
- Built with `python scripts/build.py sensecap-watcher --language en-US --wake-word wn9_alexa`, then `sdkconfig` switched to `CONFIG_USE_CUSTOM_WAKE_WORD=y`, `CONFIG_CUSTOM_WAKE_WORD="marco"`, `CONFIG_SR_MN_EN_MULTINET7_QUANT=y` and `idf.py build`. Configs and image hashes in `data/firmware-backup/xiaozhi/` (gitignored).
- **No device-side AEC** for this board (not offered in Kconfig); AFE with VAD only. `SEND_WAKE_WORD_DATA=y`: the wake-word audio goes to the server, which echoes it as the first transcript.
- **Server: xiaozhi.me** (`OTA_URL` = `https://api.tenclass.net/xiaozhi/ota/`, then MQTT `api.tenclass.net:8883`). Activated with a 6-digit code on the xiaozhi.me console. Reply language and voice are per agent in the xiaozhi.me console ("Configure role"), not in the firmware: the default agent answers in Chinese. Self-hosting is possible with `xinnan-tech/xiaozhi-esp32-server`.
- Wi-Fi provisioning: device hotspot `Xiaozhi-5AFD`, page `http://192.168.4.1`, 2.4 GHz only. Holding the wheel ~10 s factory-resets XiaoZhi's NVS (Wi-Fi + activation).
- **Console log** (115200, no prompt): user transcript `I (…) Application: >> <text>`, reply `Application: << <text>`, wake `Application: Wake word detected: Marco`, states `StateMachine: State: idle -> connecting -> listening -> speaking`. After a reply it goes back to listening, so nearby speech also gets transcribed until it goes idle (click the wheel to end).
- Measured latency (device clock): wake word → listening 0.32 s, wake word → first reply text 1.25 s, end of speech → reply text ~0.4–0.5 s (SenseCraft: 5–8 s).
- `receiver.py --voice PORT` reads XiaoZhi transcripts too and drops the wake-word echo. **Give PORT explicitly**: `find_console()` looks for `SenseCAP>`, which XiaoZhi doesn't print.
- **SenseCraft-only, will not work on XiaoZhi** (code kept unchanged): `control.py` task-flow loading / `export` / `add-http` / `battery` (no `SenseCAP>` console), HTTP and UART alarms from task flows, and `receiver.py --voice` push-to-talk via `vi: sst_text:`.
- Flashing: esptool reads/writes fail at ≥ 460800 baud on this USB bridge; use **`-b 230400`**. Port = the higher-numbered "B" one (`/dev/cu.usbmodem…123`); the other is the Himax. Flash only the files in `build/flash_args` (never a merged image, never `erase-flash`); XiaoZhi's partition table also has `nvsfactory` at 0x9000, 200K, and nothing writes there.
- **Restore factory SenseCraft**: `esptool --chip esp32s3 -p <port> -b 230400 write-flash 0 data/firmware-backup/full-2CF7F1C98280008C-2026-10-22.bin` (~26 min), then reset. Hashes and details in `data/firmware-backup/README.md`. Seeed's only GitHub release is `fw-v1.1.7` (2024-10); the full dump is preferred.

## Not yet verified on real hardware
The console client was tested only against `tools/fake_watcher.py`. On first hardware run, check: which port has the console, that the prompt text matches, that a loaded flow actually runs, and that a real alarm reaches the receiver. If real console output differs, update `fake_watcher.py` to match so tests stay meaningful.

## Conventions
- Python 3.10+, stdlib first; only dependency is `pyserial`.
- Keep `fake_watcher.py` in sync with real device behaviour and keep the end-to-end test green.
- Work-related text in English.
