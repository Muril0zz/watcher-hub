"""Test ONE servo on its own (works even if the rest of the chain is unplugged): torque on with a
limit, small move each way, logging supply voltage, load and position; aborts if the supply sags.
Usage: python servo_probe.py PORT MOTOR_ID [delta_steps] [torque_limit]"""
import sys
import time

import scservo_sdk as scs

port_name, motor = sys.argv[1], int(sys.argv[2])
delta = int(sys.argv[3]) if len(sys.argv) > 3 else 60
limit = int(sys.argv[4]) if len(sys.argv) > 4 else 500
port, pk = scs.PortHandler(port_name), scs.PacketHandler(0)
port.openPort()
port.setBaudRate(1_000_000)


def _read(fn, a):
    for _ in range(4):  # a single lost packet is not a brownout
        v, res, _ = fn(port, motor, a)
        if res == scs.COMM_SUCCESS:
            return v
        time.sleep(0.05)
    raise RuntimeError("no reply 4 times in a row (supply dropped?)")


def r1(a):
    return _read(pk.read1ByteTxRx, a)


def r2(a):
    return _read(pk.read2ByteTxRx, a)


start = r2(56)
pk.write2ByteTxRx(port, motor, 42, start)  # goal = here before torque on
pk.write1ByteTxRx(port, motor, 41, 5)  # soft acceleration
pk.write2ByteTxRx(port, motor, 46, 150)  # slow
pk.write2ByteTxRx(port, motor, 48, limit)
pk.write1ByteTxRx(port, motor, 40, 1)
try:
    for goal in (start + delta, start, start - delta, start):
        pk.write2ByteTxRx(port, motor, 42, goal)
        for _ in range(6):
            time.sleep(0.15)
            print(f"goal {goal:5d}  pos {r2(56):5d}  load {(r2(60) & 0x3FF) / 10:5.1f}%  volt {r1(62) / 10:4.1f}  temp {r1(63)}", flush=True)
    print("RESULT: moved both ways, supply held")
except RuntimeError as e:
    print("RESULT: FAILED -", e)
finally:
    pk.write1ByteTxRx(port, motor, 40, 0)
    port.closePort()
