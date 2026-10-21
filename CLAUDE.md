# watcher-hub — project context for Claude Code

Hackathon project (team of 3): connect a **SenseCAP Watcher**, **Rokid glasses** and a **SO-ARM101** arm to help elderly people in daily life. Specific use case not chosen yet. This repo is the Watcher side: a laptop controls the Watcher and receives its alarms, then forwards them to the other devices.

Approach decided: **code-first, local**. Control the Watcher over its USB-C serial console; receive alarms by HTTP push over Wi-Fi. No SenseCraft cloud API is used from code.

## Layout
- `watcher/control.py` — USB-C console client: load task flows (`load <preset|file.json>`), `export`, `battery`, `rgb`, `reboot`, `cmd`, `monitor`, `ports`. `build_flow()` makes preset flows.
- `watcher/receiver.py` — HTTP server (default `0.0.0.0:8887`) for the Watcher's alarm POSTs; also `--mode uart` for the Grove port. Writes `data/events.jsonl` and `data/images/`. **Integration hook: `on_event(evt)`** — that is where forwarding to the arm / glasses goes.
- `flows/*.json` — preset task flows (person, gesture, pet).
- `tools/fake_watcher.py` — simulated Watcher (virtual serial console + fake HTTP pushes). Use it whenever the hardware is not plugged in.
- `tests/test_end_to_end.py` — receiver + fake Watcher + control, no hardware.
- `docs/taskflow-blocks-reference.md` — official parameters of every task-flow block.

## Commands
```bash
./setup.sh                                   # venv + deps + tests + ports + LAN IP
source .venv/bin/activate
python -m unittest discover -s tests -v      # run after every change
python watcher/receiver.py                   # receive alarms
python watcher/control.py ports
python watcher/control.py -p <PORT> battery  # find the console port
python watcher/control.py -p <PORT> load gesture
python tools/fake_watcher.py --push http://127.0.0.1:8887   # no hardware
```

## The device
- Unit name "Marco", **factory SenseCraft firmware**, EUI `2CF7F1C98280008D`, SenseCraft Remote Control ON (a task sent from the app replaces one loaded over USB).
- App setting **HTTP Message Block** must be `http://<laptop-LAN-IP>:8887`. Laptop and Watcher on the same Wi-Fi; allow incoming 8887 in the firewall.
- USB-C usually enumerates **two** serial ports (ESP32 + Himax AI chip). The `SenseCAP>` console is on the ESP32 one, 115200 baud. If `battery` prints nothing, try the other port.

## Protocol facts (verified in firmware source, Seeed-Studio/SenseCAP-Watcher-Firmware `examples/factory_firmware`)
- **Alarms are push-only**: the Watcher sends something only when a running task fires. There is no status polling API.
- HTTP push: `POST <URL>/v1/notification/event`, JSON `{"requestId","deviceEui","events":{"timestamp"(ms),"text","img"(base64 JPEG 240x240),"data":{"sensor":{"temperature","humidity","CO2"},"inference":{...}}}}`. Headers `Authorization: <token>`, `API-OBITER-DEVICE-EUI`. Reply `{"code":200}`. (`task_flow_module/tf_module_http_alarm.c`)
- UART (Grove port): 115200 8N1, one JSON line per alarm `{"prompt","big_image","small_image","inference"}` ending `\r\n`. (`tf_module_uart_alarm.c`)
- Console (`main/app/app_cmd.c`): `taskflow -i -j` prints `Please input taskflow json:` then reads ONE line of JSON (max 100 KB); `taskflow -e` exports; `battery`, `rgb -r -g -b -m`, `reboot`, `record`, `vi_ctrl`, `wifi_sta`, `factory_info`, `help`.
- BLE alternative (what the app uses, `main/app/at_cmd.c`, `app_ble.c`): service `49535343-FE7D-4AE5-8FA9-9FAFD205E455`, write `49535343-8841-43F4-A8D4-ECBE34729BB3`, notify `49535343-1E4D-4BD9-BA61-23C647249616`; frames `AT+taskflow={json}\r\n`, `AT+devicecfg=`, `AT+localservice=` (sets HTTP push URL), `AT+emoji=`. Not implemented yet.
- Task flow = JSON graph of blocks: `ai camera` | `timer` → `alarm trigger` | `image analyzer` → `http alarm` | `uart alarm` | `local alarm` | `sensecraft alarm`. `tlid`/`ctd` = unique ids (use a timestamp).
- Built-in Himax models (`ai camera.params.model_type`): 1 person (`person`), 2 pet (`dog`,`cat`), 3 gesture (`paper` = open palm). 0 = cloud model by URL. Condition `{"class":X,"mode":1,"type":2,"num":0}` means "count of X > 0".
- `http alarm` URL/token are NOT in the flow; they come from the app's HTTP Message Block setting.

## Not yet verified on real hardware
The console client was tested only against `tools/fake_watcher.py`. On first hardware run, check: which port has the console, that the prompt text matches, that a loaded flow actually runs, and that a real alarm reaches the receiver. If real console output differs, update `fake_watcher.py` to match so tests stay meaningful.

## Conventions
- Python 3.10+, stdlib first; only dependency is `pyserial`.
- Keep `fake_watcher.py` in sync with real device behaviour and keep the end-to-end test green.
- Work-related text in English.
