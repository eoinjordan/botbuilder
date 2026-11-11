# SPDX-License-Identifier: MIT
"""Find the zero of one servo by small steps.

    python scripts/calibrate.py --joint left_hip_roll                  (simulator)
    python scripts/calibrate.py --joint left_hip_roll --tcp 127.0.0.1:8766
    python scripts/calibrate.py --joint left_hip_roll --tcp <uno-q>:8766 --real
    python scripts/calibrate.py --joint left_hip_roll --serial COM7 --real

Only the chosen joint moves. Type + or - and Enter to nudge it by --step
degrees (the firmware refuses more than 2), z to take the present position as
the joint's zero, q to finish. The zero is held in RAM on the board; to keep
it, write the printed value into config/calibration.json and regenerate.
Mount the horn so the joint is near its neutral position at servo mid travel
first; this routine trims the last few degrees, it does not replace that.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from microduck import player, protocol  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--joint", required=True, choices=protocol.JOINTS)
    parser.add_argument("--step", type=float, default=1.0)
    parser.add_argument("--tcp", metavar="HOST:PORT")
    parser.add_argument("--serial", metavar="PORT")
    parser.add_argument("--real", action="store_true", help="allow a link to hardware")
    args = parser.parse_args()
    index = protocol.JOINTS.index(args.joint)
    try:
        if args.serial:
            link = player.SerialLink(args.serial, real=args.real)
        elif args.tcp:
            host, _, port = args.tcp.rpartition(":")
            link = player.TcpLink(host, int(port), real=args.real)
        else:
            link = player.SimLink()
    except player.HardwareNotAllowed as error:
        print(f"refused: {error}", file=sys.stderr)
        return 2
    try:
        print(link.send("S"))
        print("E ->", link.send("E"))
        print("C ->", player.calibrate_step(link, index, "begin"))
        for raw in sys.stdin:
            key = raw.strip()
            if key in ("+", "-"):
                print(player.calibrate_step(link, index, key, args.step))
            elif key == "z":
                reply = player.calibrate_step(link, index, "zero")
                print(reply)
                if reply.startswith("ZERO"):
                    print(f'set "zero_deg": {reply.split()[2]} for {args.joint} in config/calibration.json')
            elif key == "q":
                break
            if isinstance(link, player.SimLink):
                link.wait_until(link.now_ms() + 200)
        print("X ->", player.calibrate_step(link, index, "end"))
    finally:
        link.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
