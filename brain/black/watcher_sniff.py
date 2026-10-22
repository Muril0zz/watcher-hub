"""Record both Watcher USB serial ports for N seconds to see where (and whether) the XiaoZhi firmware
logs what it heard. Usage: python watcher_sniff.py [seconds]"""
import sys
import threading
import time

import serial

SECONDS = float(sys.argv[1]) if len(sys.argv) > 1 else 120
OUT = "/Users/muriloleitefilho/.claude/jobs/1c0fc05f/tmp/"


def sniff(port: str, name: str):
    try:
        s = serial.Serial(port, 115200, timeout=0.2)
    except Exception as e:
        print(name, "open failed:", e, flush=True)
        return
    end = time.time() + SECONDS
    with open(OUT + f"watcher_{name}.txt", "w") as out:
        while time.time() < end:
            line = s.readline()
            if line:
                out.write(f"{time.strftime('%H:%M:%S')} {line.decode('utf-8', 'replace')}")
                out.flush()


threads = [threading.Thread(target=sniff, args=(f"/dev/cu.usbmodem5B6F011012{n}", f"port{n}")) for n in (1, 3)]
for t in threads:
    t.start()
for t in threads:
    t.join()
print("done", flush=True)
