"""Marco (SenseCAP Watcher on the XiaoZhi firmware) over USB: its console prints
'Application: >> <what it heard>' for every transcript. This reads those lines and hands the text to a
callback; used by the white-arm server (brain/black/server.py has its own copy of the same loop).

Only one program can hold the Watcher's serial port: run the bridge in ONE server at a time.
"""
import re
import threading
import time

HEARD = re.compile(r"Application: >> (.+?)\s*$")
WAKE_WORDS = {"marco", "mark", "hey marco", "小智", "你好小智"}
# one-word answers to Marco's own questions are conversation, not commands ("Yes." made an arm nod)
SMALL_TALK = {"yes", "no", "ok", "okay", "yeah", "yep", "nope", "sure", "thanks", "thank you", "sim", "não", "nao",
              "tá", "ta", "beleza", "好", "好的", "是", "是的", "不", "不是", "对", "嗯", "谢谢"}
# appended to the transcript so the planner knows it was addressed to the robot and may be misheard
NOTE = ("\n(Heard by the robot's own microphone right after its wake word 'Marco', so it IS meant for the robot. "
        "Its speech recognizer often mishears: map sound-alikes to the closest request, e.g. 'grow right' -> go "
        "right, 'pick up the rat cop' -> pick up the red cup. 'Marco'/'Mark' is just its name.)")


def start(on_text, log=print):
    """Run the bridge in a daemon thread; on_text(text) gets every command Marco heard."""

    def loop():
        import serial
        from serial.tools import list_ports

        while True:
            ports = [p.device for p in list_ports.comports() if (p.vid, p.pid) == (0x1A86, 0x55D2)]
            if not ports:
                time.sleep(3)
                continue
            for dev in sorted(ports, reverse=True):  # the ESP32 console is the higher-numbered port
                try:
                    with serial.Serial(dev, 115200, timeout=1) as port:
                        log(f"watcher bridge listening on {dev}")
                        while True:
                            m = HEARD.search(port.readline().decode("utf-8", "replace"))
                            if not m:
                                continue
                            heard = m.group(1).strip()
                            key = heard.lower().strip(" .!?,。！，")
                            if key in WAKE_WORDS or key in SMALL_TALK:
                                continue
                            log(f"[watcher] {heard}")
                            threading.Thread(target=on_text, args=(heard,), daemon=True).start()
                except Exception as e:  # unplugged, busy, reset: try again
                    log(f"watcher bridge: {e}")
                    time.sleep(3)

    threading.Thread(target=loop, daemon=True).start()
