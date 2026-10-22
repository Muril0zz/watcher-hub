"""Move ONE servo without talking to it while it moves (motor noise can garble the bus), then check
afterwards whether it reached the goal and still has torque (= the supply did not drop).
Usage: python servo_blind.py PORT MOTOR_ID [delta_steps] [torque_limit]"""
import sys
import time

import scservo_sdk as scs

port_name, motor = sys.argv[1], int(sys.argv[2])
delta = int(sys.argv[3]) if len(sys.argv) > 3 else 60
limit = int(sys.argv[4]) if len(sys.argv) > 4 else 300
port, pk = scs.PortHandler(port_name), scs.PacketHandler(0)
port.openPort()
port.setBaudRate(1_000_000)


def read(fn, a):
    for _ in range(10):
        v, res, _ = fn(port, motor, a)
        if res == scs.COMM_SUCCESS:
            return v
        time.sleep(0.1)
    return None


start = read(pk.read2ByteTxRx, 56)
print("start", start, "volt", (read(pk.read1ByteTxRx, 62) or 0) / 10)
pk.write2ByteTxRx(port, motor, 42, start)
pk.write1ByteTxRx(port, motor, 41, 3)
pk.write2ByteTxRx(port, motor, 46, 100)
pk.write2ByteTxRx(port, motor, 48, limit)
pk.write1ByteTxRx(port, motor, 40, 1)
for goal in (start + delta, start - delta, start):
    pk.write2ByteTxRx(port, motor, 42, goal)
    time.sleep(2.0)  # no reads while it moves
    pos, torque = read(pk.read2ByteTxRx, 56), read(pk.read1ByteTxRx, 40)
    volt = read(pk.read1ByteTxRx, 62)
    reached = pos is not None and abs(pos - goal) < 25
    print(f"goal {goal}: pos {pos} torque {torque} volt {(volt or 0) / 10:.1f} -> "
          f"{'REACHED' if reached else 'NOT reached'}{'' if torque else ' (torque lost = servo rebooted)'}", flush=True)
pk.write1ByteTxRx(port, motor, 40, 0)
port.closePort()
