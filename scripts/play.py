# SPDX-License-Identifier: MIT
"""Play a trajectory CSV on the simulator, or on the robot with --real.

    python scripts/play.py trajectories/stand.csv
    python scripts/play.py trajectories/gait.csv --tcp 127.0.0.1:8766
    python scripts/play.py trajectories/stand.csv --tcp <uno-q-address>:8766 --real
    python scripts/play.py trajectories/stand.csv --serial COM7 --real

Without --real nothing but the simulator or a socket on this machine is ever
opened. Read docs/sim-to-real.md before using --real.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from microduck import gait, player, protocol  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("trajectory", type=Path)
    parser.add_argument("--tcp", metavar="HOST:PORT", help="App Lab agent or scripts/virtual_robot.py")
    parser.add_argument("--serial", metavar="PORT", help="header UART through a USB serial adapter")
    parser.add_argument("--real", action="store_true", help="allow a link to hardware")
    parser.add_argument("--no-enable", action="store_true", help="do not send E first")
    args = parser.parse_args()

    cal = protocol.load_calibration()
    trajectory = gait.read_csv(args.trajectory)
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
    if link.hardware:
        print("Driving hardware. Keep a hand on the power switch.", file=sys.stderr)
    try:
        result = player.play(link, trajectory, cal, enable=not args.no_enable)
    finally:
        link.close()
    print(result)
    if isinstance(link, player.SimLink):
        sim = link.sim
        print(f"simulator: fell={sim.fell_at is not None} at={sim.fell_at} how={sim.fell_how} "
              f"torso={[round(float(v), 3) for v in sim.torso_pos()]} tilt={sim.tilt_deg():.1f} deg")
    return 0 if result["stopped_at_ms"] is None else 1


if __name__ == "__main__":
    sys.exit(main())
