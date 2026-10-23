"""Open the gripper, then turn the wrist roll in small steps in one direction, checking the servo still
answers after each step (stops at the first sign of trouble). Only ids 5 and 6 get torque.
Usage: python white_roll_steps.py [total_degrees, negative = the other way] [step_degrees]"""
import sys
import time

import scservo_sdk as scs

PORT = "/dev/tty.usbmodem5B7A0010951"
total = float(sys.argv[1]) if len(sys.argv) > 1 else -90
step = abs(float(sys.argv[2])) if len(sys.argv) > 2 else 10
STEPS_PER_DEG = 4096 / 360

p, k = scs.PortHandler(PORT), scs.PacketHandler(0)
p.openPort()
p.setBaudRate(1_000_000)


def rd(i, a, n=2):
    for _ in range(4):
        v, res, _ = (k.read2ByteTxRx if n == 2 else k.read1ByteTxRx)(p, i, a)
        if res == scs.COMM_SUCCESS:
            return v
        time.sleep(0.05)
    return None


def hold(i, speed, limit):
    k.write2ByteTxRx(p, i, 48, limit)
    k.write2ByteTxRx(p, i, 46, speed)
    k.write1ByteTxRx(p, i, 41, 8)
    k.write2ByteTxRx(p, i, 42, rd(i, 56))
    k.write1ByteTxRx(p, i, 40, 1)


# open the gripper first
hold(6, 300, 500)
k.write2ByteTxRx(p, 6, 42, rd(6, 11) - 40)
time.sleep(1.5)
print("gripper open at", rd(6, 56), flush=True)

hold(5, 150, 400)
lo, hi = rd(5, 9) + 40, rd(5, 11) - 40
start = rd(5, 56)
sign = 1 if total > 0 else -1
done = 0.0
while done < abs(total):
    done = min(abs(total), done + step)
    goal = max(lo, min(hi, round(start + sign * done * STEPS_PER_DEG)))
    k.write2ByteTxRx(p, 5, 42, goal)
    time.sleep(0.4)
    pos, torque, load, volt = rd(5, 56), rd(5, 40, 1), rd(5, 60), rd(5, 62, 1)
    if pos is None or not torque:
        print(f"STOP at {done:.0f} deg: wrist servo dropped out (pos {pos}, torque {torque})", flush=True)
        break
    print(f"{sign * done:+5.0f} deg  pos {pos}  load {load & 0x3FF}  {volt / 10} V", flush=True)
    if goal in (lo, hi):
        print("reached the servo's limit", flush=True)
        break
