"""Spin ONE servo continuously (wheel mode) a few seconds each way so you can watch the output horn,
then put it back in position mode. Reports how far the shaft actually turned.
Usage: python servo_spin.py PORT MOTOR_ID [seconds_each_way] [speed] [torque_limit] [--one-way]"""
import sys
import time

import scservo_sdk as scs

port_name, motor = sys.argv[1], int(sys.argv[2])
secs = float(sys.argv[3]) if len(sys.argv) > 3 else 4
speed = int(sys.argv[4]) if len(sys.argv) > 4 else 400
limit = int(sys.argv[5]) if len(sys.argv) > 5 else 400
one_way = "--one-way" in sys.argv
port, pk = scs.PortHandler(port_name), scs.PacketHandler(0)
port.openPort()
port.setBaudRate(1_000_000)
ADDR_MODE, ADDR_LOCK, ADDR_TORQUE, ADDR_SPEED, ADDR_LIMIT, ADDR_POS = 33, 55, 40, 46, 48, 56


def read(fn, addr):
    for _ in range(5):
        try:  # the SDK itself throws on a truncated reply
            v, res, _ = fn(port, motor, addr)
        except IndexError:
            res = None
        if res == scs.COMM_SUCCESS:
            return v
        time.sleep(0.05)
    return None


def pos():
    return read(pk.read2ByteTxRx, ADDR_POS)


def set_mode(m):
    pk.write1ByteTxRx(port, motor, ADDR_TORQUE, 0)
    pk.write1ByteTxRx(port, motor, ADDR_LOCK, 0)
    pk.write1ByteTxRx(port, motor, ADDR_MODE, m)
    pk.write1ByteTxRx(port, motor, ADDR_LOCK, 1)


try:
    set_mode(1)  # wheel: Goal_Speed sets rotation speed, bit 15 = direction
    pk.write2ByteTxRx(port, motor, ADDR_LIMIT, limit)
    pk.write1ByteTxRx(port, motor, ADDR_TORQUE, 1)
    runs = (("forward", speed),) if one_way else (("forward", speed), ("backward", speed | 0x8000))
    for label, value in runs:
        before, samples = pos(), []
        pk.write2ByteTxRx(port, motor, ADDR_SPEED, value)
        end = time.time() + secs
        reboots = 0
        while time.time() < end:
            time.sleep(0.25)
            samples.append(pos())
            if read(pk.read1ByteTxRx, ADDR_TORQUE) == 0:  # rebooted: torque and wheel speed are gone
                reboots += 1
                pk.write1ByteTxRx(port, motor, ADDR_TORQUE, 1)
                pk.write2ByteTxRx(port, motor, ADDR_SPEED, value)
        pk.write2ByteTxRx(port, motor, ADDR_SPEED, 0)
        seen = [s for s in samples if s is not None]
        changes = sum(1 for a, b in zip(seen, seen[1:]) if abs(a - b) > 10)
        print(f"{label}: {reboots} reboots in {secs:.0f}s; start {before}, readings {seen[:6]}..., moving in {changes} of {len(seen) - 1} intervals,"
              f" {len(samples) - len(seen)} lost readings", flush=True)
        time.sleep(0.5)
finally:
    pk.write2ByteTxRx(port, motor, ADDR_SPEED, 0)
    set_mode(0)  # back to position mode, torque off
    print("back to position mode, torque off")
    port.closePort()
