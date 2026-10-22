# SO-101 arm panel

A local web panel that drives the SO-ARM101 follower arm (6× Feetech STS3215 servos) by
**voice, buttons or sliders**, built for older people: plain-language commands, a big-button
"Simple mode", a stop word that always works, and motor protection. The SenseCAP Watcher can
send it what it hears through `watcher/arm_bridge.py`.

## Quick path

1. Plug the arm's driver board (USB) and its **12 V** supply. Put the arm in a resting pose.
2. Install and download the browser models (once):
   ```bash
   cd arm
   python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
   ./fetch_assets.sh            # add --sim for the MuJoCo model
   ```
3. Check the motors, then start the panel:
   ```bash
   .venv/bin/python check_motors.py      # expect "6/6 motors responding"
   .venv/bin/python panel.py             # http://127.0.0.1:8101
   ```
4. Open **http://127.0.0.1:8101 in Chrome** (camera and voice need it), press
   **🎤 Start listening** and say *"encendete"*, then *"abrí la mano"*.

> The serial port is set in `so101.py` (`PORT`). Only one program can use it at a time.

## What you can say

Spanish (any of vos / tú / usted) and English. A phrase made only of a stop word always stops the arm.

| Intent | Spanish | English |
|--------|---------|---------|
| Power on / rest | encendete · descansá | turn on · go to sleep |
| Hand | abrí / cerrá la mano · agarrá · soltalo | open · close · grab · release |
| Base | girá a la izquierda · un poco más | turn left · a bit more |
| Arm | levantá / bajá el brazo · estirá | raise / lower · extend |
| Fun | saludá · gracias | wave · thank you |
| **Stop** | **pará · basta · quieto** | **stop · halt · freeze** |
| Places | guardá esta posición como mesa · andá a la mesa | save this position as table · go to the table |
| Fetch | traeme el vaso | bring me the cup |

Precise wording also works: *"motor 1 a 30"*, *"codo +15"*, *"abre la pinza 50%"*.

## Fetching a cup with the wrist camera

The camera rides on the arm, so the panel uses **look → align → reach**: from a taught search pose
it turns the base until the cup is centered, then the cup's height in the image tells how far to
reach (interpolated from 2+ taught examples).

| Step | Say | What happens |
|------|-----|--------------|
| 1. Search pose (once) | guardá la posición de búsqueda | Remembers where to look from |
| 2. Mark | marcá el vaso | Finds the cup and centers it |
| 3. Free the arm | aflojate | Torque off in place after a 3 s warning: **hold the arm** |
| 4. Teach | (move the open gripper around the cup) guardá el agarre | Saves one example |
| 5. Use | traeme el vaso | Look, align, reach, grab, bring |

Use an **opaque, brightly colored** cup with *Find the cup by: Color* (click it in the video).
A place named `entrega` is where fetched things are delivered.

## Safety built in

| Risk | Protection |
|------|-----------|
| Arm drops when torque is released | Returns to its base pose first; refuses to release if it can't get there |
| Pushing against an obstacle | Stall detection stops the joint |
| Overheating | At 60 °C, or a servo "overheat" flag, it goes to rest and releases |
| Held up for a long time | After 3 min without commands it goes to rest |
| Gripper squeezing too hard | Light grip after closing; eases off on an "overload" flag |
| 12 V supply cutting out | Detected (all servos reboot) and shown as "⚡ Power cut" |
| Other websites / the LAN | Panel listens on 127.0.0.1 only, checks Host/Origin, JSON only |

## Files

| File | Role |
|------|------|
| `panel.py` | HTTP server: owns the serial bus, safety logic, places, calibration |
| `panel.html` | UI + interpreter: voice, commands, camera, hand tracking, vision grasping |
| `so101.py` | Bus helpers: sync writes, stall detection, safe return-and-release |
| `check_motors.py` | Read-only health check |
| `reset_calibration.py` | Restores the factory homing offsets |
| `secuencia.py` | Scripted pose sequence (a wave) |
| `sim_primera.py` | MuJoCo simulation (`mjpython sim_primera.py`) |

## Watcher integration

```bash
python watcher/receiver.py --voice --arm --token <secret> --eui <device EUI>
```

Voice transcripts and the open-palm gesture are forwarded to `POST /api/command`; the panel page
runs them through the same interpreter. `--arm` requires `--token`, since the receiver listens on
the LAN. The page must be open for commands to run.
