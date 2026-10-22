# AI Companion — Hackathon Handoff

Oct 23, 2026 · Murilo Leite Filho · live version: https://claude.ai/artifact/5NkfzTSwq1ZM4ye7HPtkMt

> [!CAUTION]
> **ACTION REQUIRED, for the teammate who set up Marco on xiaozhi.me: make Marco drive the arm over Wi-Fi** (only your account can do this; keep Marco in your account, do NOT remove it). About 15 minutes, on the Mac that has the black arm plugged in:
>
> 1. On the Mac, the arm server must be running WITHOUT the USB bridge (otherwise every command would run twice): `cd brain/black && ../../.venv/bin/python -u server.py /dev/tty.usbmodem5B790830241 preto --no-watcher`
> 2. xiaozhi.me → 控制台 → Marco's agent → **MCP接入点** (MCP access point): copy the `wss://api.xiaozhi.me/mcp/?token=...` address. It is a secret: do not paste it in the repo or a group chat.
> 3. In a second terminal on the Mac: `cd brain/black && MARCO_MCP_ENDPOINT='wss://...the address...' ../../.venv/bin/python marco_mcp.py` and leave it running. It prints "connected to Marco's MCP access point"; the console page should then list the tools `move_arm` and `stop_arm`.
> 4. xiaozhi.me → Marco's agent → **配置角色**: pick a Chinese + English voice (中英) and paste into 角色介绍: *You are Marco, the voice of a robot arm on the table. When the user asks the arm to move or gesture, ALWAYS call the move_arm tool with their request in their own words, then confirm in at most five words, like "OK, turning right". If they say stop, call stop_arm. Never say you cannot move the arm. Answer in the language the user spoke (Chinese, Cantonese or English).* Save.
> 5. Test: "Marco, move the arm all the way down" → the arm moves and Marco says "OK". Marco no longer needs the USB cable (only power); the Mac must stay on, online, with the arm plugged in and both programs running.
>
> Tested: `marco_mcp.py` against a simulated access point (`test_marco_mcp.py`): initialize, tools/list, tools/call (the arm turned 20 deg), ping all OK. Not yet tested against the real xiaozhi.me endpoint.

## TL;DR

The black arm is demo-ready: you talk to it in any language (from the Mac page or through Marco, the SenseCAP Watcher) and it moves, with Claude understanding the request and a spoken reply in the same language. The white arm is blocked by a faulty elbow servo; everything for vision-based picking is written but untested on hardware.

| Part | Status | Notes |
| --- | --- | --- |
| Black arm + voice brain | Working | Verified on the arm: turns, up/down, "all the way", gestures, multi-step sentences, 6 languages, noise ignored |
| Marco (Watcher) -> black arm | Working over USB | Marco's own cloud assistant still answers "I can't move the arm": turn Marco's knob to minimum and let the Mac answer |
| White arm | Blocked | Elbow servo (ID 3) is damaged: replace with a new STS3215 12 V |
| Vision pick/push (white arm, wrist camera) | Code written, not tested | Needs a working elbow first |
| Rokid glasses | Not started | Needs an Android phone + Rokid developer keys |

First thing tomorrow:

1. Get a new STS3215 12 V servo from the Seeed mentors for the white arm's elbow (section 6).
2. Get access to the xiaozhi.me account Marco is bound to, so Marco answers correctly and can work without a cable (section 3).
3. Build the pitch deck (section 8) and rehearse the black-arm demo.

## What works today: the black arm

The black arm (SO-101 leader, 5 V / 3 A supply, no camera, a trigger instead of a gripper) obeys spoken commands in any language. Every behaviour below was checked by reading the joint angles before and after, not by trusting the reply.

**How a command flows**

1. Audio comes from the Mac page (hold the button or the space bar) or from Marco over USB.
2. Local Whisper (`whisper-small`, Apple MLX) transcribes in about 1 s and detects the language. Silence, faint noise and Whisper's known hallucinations ("Thank you.", subtitle credits) are dropped here.
3. Routing: a very short pt/en command the keyword parser fully understands ("sobe tudo", "turn left") runs instantly. Anything longer, negated or in another language goes to Claude.
4. Claude Haiku 5.5 (about 1.5-2 s from China) maps the sentence onto ~20 safe intents, writes a one-line reply in the speaker's language, and marks side conversations as not for the robot (the arm stays still and silent).
5. Intents run one after the other, each waiting until the arm arrives. A new command or "stop/para/停" cancels the rest at once.
6. The Mac speaks the reply with a matching voice (pt Luciana, en Samantha, zh Tingting, yue Sinji, es Paulina, hi Lekha).

**What it can do**

| Ask | Result on the arm |
| --- | --- |
| Turn left / right | 50 deg ("a bit" 20, "all the way" to 95 deg, "30 degrees" exact) |
| Up / down | half the range ("all the way down" = a bow that stays above the table) |
| Wrist | tilt up/down, 90 deg turn, full roll |
| Hand | open / close (weak trigger: it cannot hold objects) |
| Gestures | wave, yes (nod), no (shake), dance/show, faster, slower |
| Free movement: "make a snake", "go diagonal", "bend each joint one at a time", "draw an 8 in the air" | Claude writes its own choreography (up to 40 poses, each joint + duration); the server clamps every pose to the safe ranges |
| Impossible asks ("bring me water", "make coffee") | kind refusal in the speaker's language + a "no" shake |

**Named joints** (say them in any language, e.g. "move number 2 all the way down", "junta 3 pra cima e pra baixo"):

| Name | Joint | Range used |
| --- | --- | --- |
| base | turns the whole arm | -95 (right) .. +95 (left) |
| number 1 | shoulder | -30 (back) .. 0 (vertical) .. +38 (forward, lowest) |
| number 2 | elbow | -100 (forearm up) .. -40 (forearm down) |
| number 3 | wrist bend | -60 (down) .. +60 (up) |
| number 4 | wrist turn | -170 .. +170 |
| hand | open / close | 0 closed .. 100 open |

**Measured**: 80/80 test phrases correct in pt, en, zh, Cantonese, es and hi (`test_phrases.py`, `test_phrases2.py`); free-movement phrases 10/10 (`test_keyframes.py`, checked offline, not yet on the real arm); noise tests 17/17 (`test_noise.py`). Latency from releasing the button: about 1 s for common commands, 2.5-3 s for free speech.

**Safety built in**: rising moves are staged (forearm first, then shoulder) and speed-capped so the 5 V supply does not brown out; a contact guard freezes the arm if a joint strains without moving for ~0.6 s; the server refuses out loud ("I'm not ready to move yet") instead of pretending when the arm is not ready; after a brownout it stands back up by itself.

## Marco (the Watcher) and how it drives the arm

Marco is our SenseCAP Watcher. It runs the **XiaoZhi firmware** (v2.5.2, "watcher xiaozhi agent"), not the factory SenseCraft firmware that `watcher/receiver.py` was written for. Its brain lives in the XiaoZhi cloud (xiaozhi.me, server `api.tenclass.net`); wake word **"Marco"**.

**How the link works today (USB)**

1. Marco is plugged into the Mac with a data USB-C cable (the Watcher's **bottom** port; the back port only charges).
2. The XiaoZhi firmware prints every transcript on its USB console as `Application: >> <what it heard>` (and its own answers as `<< ...`).
3. The arm server (`brain/black/server.py`, thread `watcher_bridge`) finds the Watcher by USB id `1A86:55D2`, reads those lines, drops the wake word and one-word small talk ("yes", "ok", "好的"), and sends the rest into the same brain as the Mac microphone.
4. Because Marco only listens after its wake word, its text is always treated as meant for the robot, and Claude is told Marco's recognizer mishears ("stone, the Mark grow right" correctly becomes "turn right").
5. The arm moves; the Mac speaks the correct confirmation ("Turning right all the way").

It reconnects by itself when the cable is plugged back in.

**Known problem: Marco answers "sorry, I can't move the arm"**

Marco's cloud assistant does not know an arm exists, so it apologises even though the arm does what you asked. Three fixes, best last:

- **Quick, for a demo: mute Marco.** Turn its knob all the way down. It still listens; the Mac does the talking.
- **At the start of every session, tell Marco** (it remembers within one conversation, forgets when the session restarts):

  > "Marco, from now on, when I ask you to move, the robot arm moves by itself. Just answer 'OK' and never say sorry or that you can't."
- **Permanent: change Marco's role on xiaozhi.me.** Log in with the account Marco is bound to → 控制台 (console) → the device → 配置角色 (configure role). Pick a voice that speaks Chinese and English (中英). Paste into 角色介绍 (role description):

  > You are Marco, the voice of a robot arm. The arm moves by itself whenever the user gives a command. Answer in at most 3 words, like "OK, turning right." Never say you can't move or that your tools don't work. Answer in the language the user spoke (Chinese, Cantonese or English).

  If nobody knows which account Marco is bound to, re-bind it to a team account: the Watcher shows a 6-digit code on screen, which you enter in the xiaozhi.me console.

**Without a cable (wireless): the MCP endpoint**

xiaozhi.me lets an agent call external tools through an "MCP接入点" (MCP access point): a secret `wss://api.xiaozhi.me/mcp/?token=...` address in the console. `brain/black/marco_mcp.py` (ready, see the action box at the top) connects to it and offers Marco the tool `move_arm(command)` that forwards to `http://127.0.0.1:8000/api/command`. Then Marco calls the arm itself over Wi-Fi, needs no USB cable, and stops saying it can't move (it now has the tool). This needs the console login above; the code is about one page ([an example bridge, mcp_pipe.py](https://glama.ai/mcp/servers/@suhuail/api-mcp/blob/8ccf37a0ba9be14ab7425ca4fc3f99214ec89c79/mcp_pipe.py)).

## How to run it

Everything is on GitHub in branch **`feat/claude-brain`**, folder `brain/`: on Murilo's fork `Muril0zz/watcher-hub` and in a pull request to `mehdi-loup/watcher-hub` (once merged, it is in `main`). It runs on a Mac with Apple Silicon (local Whisper uses Apple MLX).

**One-time setup**

```bash
git clone https://github.com/Muril0zz/watcher-hub.git && cd watcher-hub
git checkout feat/claude-brain
python3.12 -m venv .venv
.venv/bin/pip install feetech-servo-sdk pyserial lerobot deepdiff anthropic mlx-whisper \
    fastapi 'uvicorn[standard]' opencv-python-headless sounddevice numpy
mkdir -p ~/.config/claude-brain
echo 'ANTHROPIC_API_KEY=sk-ant-...' > ~/.config/claude-brain/.env && chmod 600 ~/.config/claude-brain/.env
```

The first run downloads `mlx-community/whisper-small-mlx` (about 480 MB) from Hugging Face. The API key file lives outside the repo on purpose: never commit it.

**Hardware**

| Device | Power | USB port on the Mac | Notes |
| --- | --- | --- | --- |
| Black arm (leader, 5 V servos) | 5 V / 3 A | `/dev/tty.usbmodem5B790830241` | Calibration `preto` in `~/.cache/huggingface/lerobot/calibration/robots/so_follower/preto.json` |
| White arm (follower, 12 V servos) | 12 V / 2 A | `/dev/tty.usbmodem5B901033751` | Elbow servo broken, see section 5 |
| Marco (Watcher) | its battery or USB | auto-detected (`1A86:55D2`) | Bottom USB-C port, data cable |
| White arm wrist camera | USB | OpenCV index 0 ("USB HD Camera") | Index can change; set `BRAIN_CAMERA` |

**Run the black arm (demo)**

```bash
cd brain/black
../../.venv/bin/python -u server.py /dev/tty.usbmodem5B790830241 preto
# open http://127.0.0.1:8000 in Chrome, hold the orange button (or space) and speak
```

The arm must be standing (upper arm roughly vertical) when the server starts. If the page says "lying / move it by hand", lift the arm upright by hand: the server takes over by itself. Options: `--no-watcher` (ignore Marco), `--watcher-quiet` (let Marco talk instead of the Mac).

**Check it before a demo (no guessing)**

- `python test_phrases.py` and `python test_phrases2.py`: 80 phrases through the real routing, no arm needed.
- `python test_noise.py`: silence, noise and side conversations are ignored.
- `python verify_moves.py "turn left" "go all the way down"`: sends commands to the running server and prints how far each joint REALLY moved.
- `python trace_moves.py "turn left then wave"`: prints the joints every 0.5 s to check multi-step order.

**Troubleshooting**

| Symptom | Cause | Fix |
| --- | --- | --- |
| Arm says "I'm not ready to move yet" | A joint is outside its range or the arm is lying down | Lift the arm upright by hand; the server takes over |
| All motors go limp mid-move | Supply brownout (motors reboot) | It stands back up by itself; avoid fast moves with everything raised |
| Nothing reaches the arm from Marco | Watcher cable out, or a charge-only cable | Bottom port, data cable; the bridge reconnects in ~3 s |
| Marco is stuck in "wifi_configuring" | Lost its Wi-Fi | Reboot it; it rejoins the 2.4 GHz network (it cannot use 5 GHz) |
| "deepdiff is required" | Missing package | `pip install deepdiff` |

## The white arm: what went wrong

The white arm's elbow servo (STS3215 12 V, bus ID 3) is damaged and must be replaced. Whenever it has to produce torque it stalls, draws more than the 12 V / 2 A supply can give, and every servo on the bus reboots. Software cannot fix it.

**Evidence (each test isolates one cause)**

| Test | Elbow (ID 3) | Healthy servo, same supply |
| --- | --- | --- |
| 3 deg move at 35% torque, logging the 12 V rail | Supply collapses to 5.3-5.6 V, all servos reboot | Shoulder and wrist: 12.0 V steady, move fine |
| Alone on the bus, 30% torque, slow, no reads while moving | Reboots on every move, never reaches the goal | Base: reaches 3/3 goals, keeps torque |
| Out of the arm, in hand, continuous rotation for 30 s | Turns only ~20% of the time (jerks and stops), 62 °C afterwards | (a free servo barely warms up) |
| Configuration registers (gain, limits, protections) | Identical to the other five | rules out a settings problem |
| By hand, unpowered | Noticeably stiffer than the other joints | |

The servo's own overload protection (load above 80% for ~2 s cuts output to 20%) explains the "jerk and stop" motion: internal friction keeps tripping it even with no load.

**Likely root causes**

- `arm/reset_calibration.py` writes homing offsets that its own comment calls "reconstructed" and removes the servos' angle limits (0-4095). Nothing then stops a joint from being driven into its hard stop at full torque, which is how STS3215 gearboxes and motors get damaged.
- The documented rest pose is fully folded, which sits on the elbow's hard stop. `arm/secuencia.py` itself notes that the folded pose "made the 12V supply cut out as soon as a motor pushed".
- Our own debugging held it stalled at full torque for 30 s once (65 °C), which cannot have helped.
- The 12 V / 2 A supply is marginal for this arm; 12 V / 5 A or more is the usual spec.

**State right now**

- The elbow servo is out of the arm. The wrist, wrist-roll and gripper servos are unplugged from the chain. Base and shoulder are fine.
- The elbow servo's homing offset was rewritten (it had ended up on the encoder's 0/4095 seam); a new servo will need its own (section 6).
- The white-arm brain keeps the elbow disabled by default (`BRAIN_DISABLED_JOINTS`, default `elbow_flex`).

**So it doesn't happen again**: write real angle limits into every servo, keep torque limits low (the brain already does), use the contact guard, and never park the arm folded against a hard stop.

## When we get a working white arm: Marco + camera picking things up

The goal: say "Marco, pick up the red cup" and the white arm finds the cup with its wrist camera and grabs it. The code for this is already in `brain/` (white-arm server, port 8200); it has only been tested without moving the arm, because the elbow broke first. Expect to tune it.

**How it will work**

1. Marco hears "pick up the red cup"; `watcher_link.py` reads it from the USB console.
2. `planner.py` sends Claude (Opus 5.5, low effort) the sentence, the current wrist-camera photo and the joint angles. Claude returns a plan such as `pick: "red cup"` and a reply in the speaker's language. Measured: about 3-5 s.
3. `executor.py` moves to the `look_table` pose and asks Claude once where the object is in the photo (`vision.find` returns a bounding box). If it is not visible, it turns the base 0, +25, -25, +45, -45 deg and asks again.
4. The base turns until the object is centred in the image (fast local template tracking, no API calls). It learns by itself which way the image moves when the base turns.
5. The arm leans in step by step, keeping the object centred, until the object fills about 45% of the image height (= within the gripper's reach).
6. The gripper closes; if it closed completely (nothing inside), it reopens and says it could not grab it. Otherwise it lifts the object.
7. "Give it to me" moves to the `give` pose and opens the gripper. "Push the phone to the left" and "point at the bottle" use the same search-and-centre steps.

**Step by step for the team**

1. **Replace the elbow servo** with a new STS3215 **12 V** (code C018). Do not reuse a servo from the black arm: those are lower-voltage servos and 12 V can burn them.
2. **Give it ID 3.** Plug only the new servo into the white arm's driver board, then: `python brain/servo_setid.py /dev/tty.usbmodem5B901033751 1 3`
3. **Test it alone before mounting** (both must pass):
   - `python brain/servo_blind.py /dev/tty.usbmodem5B901033751 3 60 300`: "REACHED" 3 times, torque stays on.
   - `python brain/servo_spin.py /dev/tty.usbmodem5B901033751 3 10 1200 600 --one-way`: turning in nearly all intervals, still cool afterwards.
4. **Mount it with the forearm at a right angle to the upper arm**, then make that pose read as the middle of the range: `python brain/rezero.py 3 2048`
5. **Re-connect the whole chain** (base, shoulder, elbow, wrist flex, wrist roll, gripper). Check that all six answer: `python brain/black/scan_arm.py /dev/tty.usbmodem5B901033751`.
6. **Get a 12 V / 5 A (or bigger) supply** from the mentors if possible. The 2 A one browns out when the arm lifts fast.
7. **Turn the elbow back on** in the brain: start the server with `BRAIN_DISABLED_JOINTS=""` (by default the elbow is disabled).
8. **Start the white-arm server with Marco**, and stop the black-arm server first (only one program can read Marco's USB port): `cd brain && BRAIN_DISABLED_JOINTS="" ../.venv/bin/python -u server.py --watcher` → open `http://127.0.0.1:8200`. Use `--dry-run` first: it plans and talks without moving.
9. **Teach the poses by hand** on the page (Release, place the arm, Save): `ready`, `up`, `forward`, `look_table` (the wrist camera must see the whole table area in front of the arm), `give` (where it hands things to the person). Never teach a pose that presses the gripper into the table.
10. **Check the camera** shows on the page. If not, set `BRAIN_CAMERA` to the right OpenCV index (it was 0).
11. **Test in this order**, each a few times with a brightly coloured, light object (under ~200 g, under ~5 cm wide): "point at the red cup" → "push the red cup to the left" → "pick up the red cup" → "give it to me".

**Knobs to tune in `brain/executor.py`** if it misbehaves: `CAMERA_HFOV` (60, how far to turn per pixel), `ALIGN_TOL` (0.04, how centred is centred), `NEAR_SIZE` (0.45, object height that means "in reach"), `SCAN` (base offsets to search), and the lean step inside `_approach` (+5 deg shoulder, +4 deg elbow, -3 deg wrist per step).

**If it never gets close enough to grab**, the simplest upgrade is the one Daniel used: teach two or three grasp poses by hand for objects at different distances, and interpolate between them from where the object sits in the image.

## Improvements for tomorrow

The two that matter most for the judges are a working white arm (section 6) and Marco answering correctly; the rest polishes the demo and the story.

| # | Improvement | Why | Effort |
| --- | --- | --- | --- |
| 1 | Set Marco's role on xiaozhi.me (section 3) | Stops "sorry, I can't"; Marco becomes the one voice | 10 min, needs the account |
| 2 | Marco → arm over the MCP endpoint (section 3) | No USB cable; Marco really "has" the arm as a tool | 1-2 h, needs the account |
| 3 | New elbow servo + vision tests (section 6) | The "pick it up for me" moment is the strongest demo | 2-3 h |
| 4 | Write real angle limits into every servo | The servos stop themselves before a hard stop; protects the new elbow | 30 min |
| 5 | Elderly-care actions: medication reminders on a schedule, open-palm "help" gesture → arm waves + alert to family | Turns the demo into the AI Companion story | 2 h |
| 6 | "What do you see?" action (Claude describes the wrist camera view out loud) | Easy wow moment, works even if grasping is flaky | 30 min |
| 7 | Rokid glasses as a remote: Android phone + Rokid developer keys; the open-source RokidAIAssistant app accepts an OpenAI-compatible endpoint, reachable with `adb reverse tcp:8000 tcp:8000` | Hands-free view for caregivers | half a day, needs keys |
| 8 | Run the server on a Raspberry Pi 5 next to the arm | The arm no longer needs the Mac | 2-3 h (replace MLX Whisper with faster-whisper) |
| 9 | Merge `feat/claude-brain` into `main`, add a README for `brain/` | Teammates find everything in one place | 30 min |

**For the live demo**: keep the black arm and Marco plugged into the Mac; turn Marco's knob down (or tell it the session sentence from section 3); speak short commands; keep a typed-command box ready on the page in case the room is too loud.

## Pitch deck: AI Companion

Build it the way our last winning deck (Proof of Field, EAG Buildathon, 1st place) was built: 10 slides in English, 1 minute of pitch, 2 minutes of live demo, the last slides kept for Q&A.

**Format rules from that deck**

- HTML slides (one `index.html`, arrow keys to move), white background, Inter for text, JetBrains Mono for numbers and code. One idea per slide, big type, real screenshots and photos of OUR hardware, no stock images, no decorative gradients.
- Every slide title is a full sentence that states the claim ("Today: three weeks, per buyer, per season."), never a label like "Problem".
- Only numbers we can defend: our measurements or a cited source, with the source on the slide.
- A timed script, two sentences the speaker repeats in every Q&A answer, an opening line learned by heart, and a fallback if the live demo breaks.

**Slide by slide**

| # | Title (the claim) | On the slide |
| --- | --- | --- |
| 1 | AI Companion: say it any way, in any language, and it lends a hand. | Photo of Marco + the arm on the table; team names |
| 2 | One in five people in China is now over 60. | 297 million people aged 60+ at the end of 2023, 21.1% of the population ([Caixin, official data](https://www.caixinglobal.com/2024-09-05/one-in-five-chinese-is-now-elderly-official-data-shows-102233777.html)) |
| 3 | Today, the voice in the room can talk, but it can't hand you anything. | Smart speakers have no hands; robots need apps, menus and one language |
| 4 | With AI Companion: Marco hears you, Claude understands, the arm does it. | Before / after: the same request with and without |
| 5 | Where the AI sits, where the hardware sits. | Diagram: Marco (wake word, ears) → Mac brain (Whisper, Claude, safety) → arm (hands) + wrist camera (eyes) |
| 6 | Live demo. | Screenshot of the control page as backup |
| 7 | Safe by design: it knows what it can't do. | Refuses impossible asks out loud, "stop" always wins, ignores side conversations, never pushes into the table |
| 8 | Under the hood: real languages, real latency. | 80/80 test phrases in 6 languages (Mandarin, Cantonese, English, Portuguese, Spanish, Hindi); ~1 s for common commands, ~3 s for free speech; 17/17 noise tests |
| 9 | Roadmap: from gestures to fetching things. | Camera picking (white arm), medication reminders, "help" palm gesture → family alert, Rokid glasses for caregivers, no cable (MCP), runs on a Raspberry Pi |
| 10 | Questions we expect. | The Q&A answers below |

**60-second pitch (slides 1 → 2 → 3 → 4 → 5, then the demo)**

- **0:00 [1]** "This is AI Companion. You talk to it the way you talk to a person, in any language, and it lends you a hand."
- **0:10 [2]** "One in five people in China is now over sixty: almost three hundred million people."
- **0:20 [3]** "The voice assistants in their homes can talk, but they can't hand anyone anything, and the robots that could need apps, menus and one language."
- **0:35 [4]** "With AI Companion, Marco listens, Claude understands what you meant, even with slang, dialect or a correction, and the arm does it, or says kindly why it can't."
- **0:50 [5]** "Marco is the ears, the arm is the hands, the camera is the eyes, and the brain runs on this laptop. Let me show you."

**2-minute demo script** (black arm; keep Marco's volume down so the Mac is the one voice)

1. "Marco" → "turn left" → "go all the way down and wave" (shows sequences and "all the way").
2. A teammate in Mandarin: "向右转一点". Then Cantonese: "舉高少少". The reply comes back in the same language.
3. A correction: "left, no, right" (it turns right).
4. Someone chats beside it ("we're having lunch later"): the arm stays still.
5. "Bring me a glass of water": it says kindly it can't, and shakes "no".
6. "Stop" in the middle of a move.

**Fallback**: if Marco or Wi-Fi fails, use the hold-to-talk button on the page; if the API fails, short commands still run offline through the keyword path.

**Two sentences to repeat in every answer**: "Say it any way, and it does it, or tells you why not." · "Claude decides; the safety layer enforces."

**Questions we expect**

- *"Why not a smart speaker?"* They have no hands. The value is the physical help: the arm acts.
- *"Is it safe around elderly people?"* Low torque limits, a contact guard that freezes the arm, a stop word that always wins, and Claude refuses anything unsafe. It is a small desk arm, not a mobile robot.
- *"Does it work offline?"* Speech recognition runs on the laptop; common commands work offline; free-form understanding needs the Claude API.
- *"What about dialects?"* Cantonese is detected and answered in Cantonese; Claude also fixes misheard words ("stone, the Mark grow right" became "turn right").
- *"Why two arms?"* The white arm carries the wrist camera for picking objects; the black arm shows the interaction today. Say plainly that the white arm's elbow servo failed during the hackathon.

## Repo map, keys, safety and open questions

**Where things are** (branch `feat/claude-brain`)

| Path | What it is |
| --- | --- |
| `brain/black/` | Black-arm voice server (port 8000): `server.py`, `claude_intents.py` (Claude prompt + schema), `routing.py` (instant path rules), `commands.py` (keyword parser), `speech.py` (Whisper + voices), `static/index.html` (hold-to-talk page) |
| `brain/black/test_*.py`, `verify_moves.py`, `trace_moves.py`, `bench_models.py` | Tests and checks (section 4) |
| `brain/black/calibrate.py`, `calibrate_joint.py`, `scan_arm.py` | Recalibrate the black arm (you hold it in the middle pose, then sweep each joint) |
| `brain/` | White-arm brain with vision (port 8200): `server.py`, `planner.py`, `vision.py`, `executor.py`, `arm.py`, `watcher_link.py` |
| `brain/servo_*.py`, `rezero.py` | Single-servo tools: test, spin, set ID, re-zero (section 6) |
| `arm/` | Daniel's original panel for the white arm. Kept for reference; do not run `reset_calibration.py` again (it removes the angle limits) |
| `watcher/` | Receiver for the Watcher's factory firmware; does not apply while Marco runs XiaoZhi |

**Keys**: the Anthropic API key lives in `~/.config/claude-brain/.env`, never in the repo. The key used during the hackathon was pasted in a chat: rotate it in the Anthropic console when the event ends. Cost is negligible: the arm uses Claude Haiku 5.5 for commands and Opus 5.5 only for camera planning.

**Safety**

- The black arm's servos are low-voltage: never connect it to the white arm's 12 V supply.
- Keep hands away during "show" and fast moves; "stop" (any language) freezes it at once.
- Never park either arm fully folded against a hard stop, and never teach a pose that presses into the table.

**Open questions**

- Who owns the xiaozhi.me account Marco is bound to?
- Do the Seeed mentors have a spare STS3215 12 V servo and a 12 V / 5 A supply?
- Can we get Rokid developer keys (`ROKID_CLIENT_SECRET` + the glasses' `sn_auth_file`) and an Android phone?
