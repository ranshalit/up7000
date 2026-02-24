import argparse
import os
import re
import sys
from typing import List, Optional


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def _maybe_reexec_in_venv() -> None:
    """Re-exec into ~/fira-venv if running under system python.

    Virtualenv activation is per-shell, so after reboot/login the user may be
    running the system interpreter again. This wrapper makes invocation
    resilient by preferring the known venv interpreter when available.
    """

    if _env("FIRA_NO_REEXEC") == "1":
        return

    # Prevent loops.
    if _env("FIRA_REEXEC") == "1":
        return

    # If already in a venv, don't re-exec.
    try:
        if sys.prefix != sys.base_prefix:
            return
    except Exception:
        return

    venv_python = os.path.expanduser("~/fira-venv/bin/python")
    if not os.path.exists(venv_python):
        return

    try:
        os.environ["FIRA_REEXEC"] = "1"
        os.execv(venv_python, [venv_python, *sys.argv])
    except Exception:
        # If re-exec fails, continue on current interpreter.
        return


def _parse_video_device(dev: str) -> int:
    m = re.fullmatch(r"/dev/video(\d+)", (dev or "").strip())
    if not m:
        raise argparse.ArgumentTypeError(f"Invalid --video-device {dev!r} (expected like /dev/video4)")
    return int(m.group(1))


def parse_args(argv: List[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generic FIRA camera runner")

    p.add_argument(
        "--camera-id",
        type=int,
        default=None,
        help="V4L2 camera numeric id (maps to /dev/videoN). Overrides FIRA_CAMERA_ID.",
    )
    p.add_argument(
        "--video-device",
        type=_parse_video_device,
        default=None,
        help="Convenience alternative to --camera-id (e.g. /dev/video4).",
    )
    p.add_argument(
        "--serial-device",
        default=None,
        help="Serial port for camera control (e.g. /dev/ttyUSB1 or /dev/ttyACM0). Overrides FIRA_CAMERA_PORT.",
    )
    p.add_argument(
        "--baud",
        type=int,
        default=None,
        help="Serial baud rate. Overrides FIRA_CAMERA_BAUD (default 115200).",
    )
    p.add_argument(
        "--headless",
        action="store_true",
        help="Disable GUI window (sets FIRA_HEADLESS=1).",
    )
    p.add_argument(
        "--gui",
        action="store_true",
        help="Force GUI window when possible (sets FIRA_HEADLESS=0).",
    )

    return p.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> None:
    _maybe_reexec_in_venv()
    args = parse_args(list(sys.argv[1:] if argv is None else argv))

    if args.camera_id is not None and args.video_device is not None and int(args.camera_id) != int(args.video_device):
        raise SystemExit(
            f"Conflicting options: --camera-id {args.camera_id} != --video-device /dev/video{args.video_device}"
        )

    camera_id = args.camera_id if args.camera_id is not None else args.video_device
    if camera_id is not None:
        os.environ["FIRA_CAMERA_ID"] = str(int(camera_id))
        # Always strict when the user explicitly provides a camera-id.
        os.environ["FIRA_STRICT_CAMERA_ID"] = "1"

    if args.serial_device:
        os.environ["FIRA_CAMERA_PORT"] = str(args.serial_device)

    if args.baud is not None:
        os.environ["FIRA_CAMERA_BAUD"] = str(int(args.baud))

    if args.headless and args.gui:
        raise SystemExit("Use only one of --headless or --gui")
    if args.headless:
        os.environ["FIRA_HEADLESS"] = "1"
    if args.gui:
        os.environ["FIRA_HEADLESS"] = "0"

    # Import after env vars are set because fira_1 reads configuration at import time.
    import importlib

    fira_1 = importlib.import_module("fira_1")
    fira_1.main()


if __name__ == "__main__":
    main()
