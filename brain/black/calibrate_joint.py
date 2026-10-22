"""Re-record the range of ONE joint of a calibrated SO-101 (e.g. the gripper was skipped).

Only that joint goes limp; the others keep their torque. Raw positions are recorded until
flags/<id>.<joint>.stop appears (or --max-seconds passes), then the joint's range is written to
the servo limits and to the saved calibration file.
Usage: python calibrate_joint.py PORT ID JOINT
"""
import argparse
import json
import time
from pathlib import Path

import scservo_sdk as scs

from calibrate import FLAGS, status

ADDR_MIN_LIMIT = 9
ADDR_MAX_LIMIT = 11
ADDR_LOCK = 55
ADDR_TORQUE = 40
ADDR_POSITION = 56
CALIB_DIR = Path.home() / ".cache/huggingface/lerobot/calibration/robots/so_follower"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("port")
    parser.add_argument("id")
    parser.add_argument("joint")
    parser.add_argument("--max-seconds", type=float, default=90)
    args = parser.parse_args()

    calib_file = CALIB_DIR / f"{args.id}.json"
    calib = json.loads(calib_file.read_text())
    servo_id = calib[args.joint]["id"]
    tag = f"{args.id}.{args.joint}"
    FLAGS.mkdir(exist_ok=True)
    stop_flag = FLAGS / f"{tag}.stop"
    stop_flag.unlink(missing_ok=True)

    port = scs.PortHandler(args.port)
    pk = scs.PacketHandler(0)
    port.openPort()
    port.setBaudRate(1_000_000)
    try:
        pk.write1ByteTxRx(port, servo_id, ADDR_TORQUE, 0)
        start, _, _ = pk.read2ByteTxRx(port, servo_id, ADDR_POSITION)
        lo = hi = start
        status(tag, "recording: move this joint end to end")
        deadline = time.time() + args.max_seconds
        while not stop_flag.exists() and time.time() < deadline:
            pos, result, _ = pk.read2ByteTxRx(port, servo_id, ADDR_POSITION)
            if result == scs.COMM_SUCCESS:
                lo, hi = min(lo, pos), max(hi, pos)
            time.sleep(0.02)

        pk.write1ByteTxRx(port, servo_id, ADDR_LOCK, 0)
        pk.write2ByteTxRx(port, servo_id, ADDR_MIN_LIMIT, lo)
        pk.write2ByteTxRx(port, servo_id, ADDR_MAX_LIMIT, hi)
        pk.write1ByteTxRx(port, servo_id, ADDR_LOCK, 1)
        calib[args.joint]["range_min"], calib[args.joint]["range_max"] = lo, hi
        calib_file.write_text(json.dumps(calib, indent=4))
        status(tag, f"done: {args.joint} {lo}-{hi}")
    finally:
        port.closePort()


if __name__ == "__main__":
    main()
