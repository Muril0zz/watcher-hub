"""Try to free a stiff servo: spin it fast and keep it spinning (restart whenever it stalls), with the
servo's overload protection relaxed but OUR temperature cut-off kept, then restore its settings.
Waits until it has cooled first. Usage: python servo_runin.py PORT MOTOR_ID [seconds] [speed]"""
import sys
import time

import scservo_sdk as scs

port_name, motor = sys.argv[1], int(sys.argv[2])
secs = float(sys.argv[3]) if len(sys.argv) > 3 else 60
speed = int(sys.argv[4]) if len(sys.argv) > 4 else 3000
COOL_START, HOT_STOP = 45, 60  # deg C
A_MODE, A_LOCK, A_TORQUE, A_SPEED, A_LIMIT, A_POS, A_TEMP, A_OVERLOAD = 33, 55, 40, 46, 48, 56, 63, 36
port, pk = scs.PortHandler(port_name), scs.PacketHandler(0)
port.openPort()
port.setBaudRate(1_000_000)


def read(fn, addr):
    for _ in range(5):
        try:
            v, res, _ = fn(port, motor, addr)
        except IndexError:
            res = None
        if res == scs.COMM_SUCCESS:
            return v
        time.sleep(0.05)
    return None


def r1(a):
    return read(pk.read1ByteTxRx, a)


def r2(a):
    return read(pk.read2ByteTxRx, a)


def eeprom(addr, value):
    pk.write1ByteTxRx(port, motor, A_TORQUE, 0)
    pk.write1ByteTxRx(port, motor, A_LOCK, 0)
    pk.write1ByteTxRx(port, motor, addr, value)
    pk.write1ByteTxRx(port, motor, A_LOCK, 1)


while (t := r1(A_TEMP)) is None or t > COOL_START:
    print(f"cooling: {t} C (starting at {COOL_START})", flush=True)
    time.sleep(5)

overload_before = r1(A_OVERLOAD)
moving = total = restarts = 0
reason = "time up"
try:
    eeprom(A_OVERLOAD, 100)  # don't cut to 20% torque after 2 s of hard work
    eeprom(A_MODE, 1)  # wheel mode
    pk.write2ByteTxRx(port, motor, A_LIMIT, 1000)
    pk.write1ByteTxRx(port, motor, A_TORQUE, 1)
    pk.write2ByteTxRx(port, motor, A_SPEED, speed)
    last, still, t0 = r2(A_POS), 0, time.time()
    while time.time() - t0 < secs:
        time.sleep(0.25)
        p, temp, tq = r2(A_POS), r1(A_TEMP), r1(A_TORQUE)
        total += 1
        if temp is not None and temp >= HOT_STOP:
            reason = f"too hot ({temp} C)"
            break
        turning = p is not None and last is not None and abs(p - last) > 20
        moving += turning
        still = 0 if turning else still + 1
        if tq == 0 or still >= 4:  # rebooted or stalled ~1 s: kick it again
            restarts += 1
            pk.write1ByteTxRx(port, motor, A_TORQUE, 1)
            pk.write2ByteTxRx(port, motor, A_SPEED, 0)
            time.sleep(0.1)
            pk.write2ByteTxRx(port, motor, A_SPEED, speed)
            still = 0
        if total % 8 == 0:
            print(f"  t={time.time() - t0:4.0f}s  turning {moving}/{total}  temp {temp} C  restarts {restarts}", flush=True)
        last = p
finally:
    pk.write2ByteTxRx(port, motor, A_SPEED, 0)
    eeprom(A_MODE, 0)
    eeprom(A_OVERLOAD, overload_before or 80)
    print(f"stopped: {reason}. Turning {moving}/{total} samples ({100 * moving // max(total, 1)}%), "
          f"{restarts} restarts, temp {r1(A_TEMP)} C. Protections restored, torque off.", flush=True)
    port.closePort()
