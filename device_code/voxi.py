import argparse
import os
import re
import sys
from typing import List, Optional


def _setenv_if(name: str, value: Optional[str]) -> None:
    if value is None:
        return
    v = str(value).strip()
    if v == "":
        return
    os.environ[name] = v


def _parse_video_device(dev: str) -> int:
    m = re.fullmatch(r"/dev/video(\d+)", (dev or "").strip())
    if not m:
        raise argparse.ArgumentTypeError(f"Invalid --video-device {dev!r} (expected like /dev/video4)")
    return int(m.group(1))


def parse_args(argv: List[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generic VOXI camera runner (wraps voxi_1.py)")

    p.add_argument(
        "--camera-id",
        type=int,
        default=None,
        help="V4L2 camera numeric id (maps to /dev/videoN). Sets VOXI_CAMERA_ID.",
    )
    p.add_argument(
        "--video-device",
        type=_parse_video_device,
        default=None,
        help="Convenience alternative to --camera-id (e.g. /dev/video2).",
    )
    p.add_argument(
        "--serial-device",
        default=None,
        help="Serial port for camera control (e.g. /dev/ttyUSB1 or /dev/ttyACM0). Sets VOXI_CAMERA_PORT.",
    )
    p.add_argument(
        "--baud",
        type=int,
        default=None,
        help="Serial baud rate. Sets VOXI_CAMERA_BAUD (default 115200).",
    )
    p.add_argument(
        "--save-dir",
        default=None,
        help="Directory for recordings. Sets VOXI_VIDEO_SAVE_DIR.",
    )

    p.add_argument("--frame-width", type=int, default=None, help="Sets VOXI_FRAME_WIDTH")
    p.add_argument("--frame-height", type=int, default=None, help="Sets VOXI_FRAME_HEIGHT")

    p.add_argument("--headless", action="store_true", help="Force VOXI_HEADLESS=1")
    p.add_argument("--gui", action="store_true", help="Force VOXI_HEADLESS=0")

    p.add_argument(
        "--no-reexec",
        action="store_true",
        help="Disable voxi_1 venv re-exec (sets VOXI_NO_REEXEC=1). Useful for GUI/X11-forwarding when venv OpenCV is headless.",
    )

    p.add_argument(
        "--strict-camera-id",
        action="store_true",
        help="If --camera-id is provided, do not fall back to other auto-detected /dev/video* nodes (sets VOXI_STRICT_CAMERA_ID=1).",
    )

    p.add_argument(
        "--max-bad-frames",
        type=int,
        default=None,
        help="Sets VOXI_MAX_BAD_FRAMES (default 3)",
    )
    p.add_argument(
        "--v4l2-timeout-s",
        type=float,
        default=None,
        help="Sets VOXI_V4L2_CTL_TIMEOUT_S",
    )
    p.add_argument(
        "--serial-timeout-s",
        type=float,
        default=None,
        help="Sets VOXI_SERIAL_TIMEOUT_S",
    )
    p.add_argument(
        "--watchdog-s",
        type=float,
        default=None,
        help="Sets VOXI_WATCHDOG_S",
    )

    p.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Set any extra environment variables (repeatable). Example: --set VOXI_LOG_FILE=/tmp/voxi.log",
    )

    return p.parse_args(argv)


def _apply_kv(items: List[str]) -> None:
    for item in items or []:
        if "=" not in item:
            raise SystemExit(f"Invalid --set value {item!r}. Expected KEY=VALUE.")
        k, v = item.split("=", 1)
        k = k.strip()
        if not k:
            raise SystemExit(f"Invalid --set value {item!r}. KEY is empty.")
        os.environ[k] = v


def main(argv: Optional[List[str]] = None) -> None:
    args = parse_args(list(sys.argv[1:] if argv is None else argv))

    if args.headless and args.gui:
        raise SystemExit("Use only one of --headless or --gui")

    if args.camera_id is not None and args.video_device is not None and int(args.camera_id) != int(args.video_device):
        raise SystemExit(
            f"Conflicting options: --camera-id {args.camera_id} != --video-device /dev/video{args.video_device}"
        )

    camera_id = args.camera_id if args.camera_id is not None else args.video_device

    _setenv_if("VOXI_CAMERA_ID", None if camera_id is None else str(int(camera_id)))
    _setenv_if("VOXI_CAMERA_PORT", args.serial_device)
    _setenv_if("VOXI_CAMERA_BAUD", None if args.baud is None else str(int(args.baud)))
    _setenv_if("VOXI_VIDEO_SAVE_DIR", args.save_dir)
    _setenv_if("VOXI_FRAME_WIDTH", None if args.frame_width is None else str(int(args.frame_width)))
    _setenv_if("VOXI_FRAME_HEIGHT", None if args.frame_height is None else str(int(args.frame_height)))
    _setenv_if("VOXI_MAX_BAD_FRAMES", None if args.max_bad_frames is None else str(int(args.max_bad_frames)))
    _setenv_if("VOXI_V4L2_CTL_TIMEOUT_S", None if args.v4l2_timeout_s is None else str(float(args.v4l2_timeout_s)))
    _setenv_if("VOXI_SERIAL_TIMEOUT_S", None if args.serial_timeout_s is None else str(float(args.serial_timeout_s)))
    _setenv_if("VOXI_WATCHDOG_S", None if args.watchdog_s is None else str(float(args.watchdog_s)))

    if args.headless:
        os.environ["VOXI_HEADLESS"] = "1"
    if args.gui:
        os.environ["VOXI_HEADLESS"] = "0"

    if args.no_reexec:
        os.environ["VOXI_NO_REEXEC"] = "1"

    if args.strict_camera_id:
        os.environ["VOXI_STRICT_CAMERA_ID"] = "1"

    _apply_kv(args.set)

    # Allow running as: python3 device_code/voxi.py
    sys.path.insert(0, os.path.dirname(__file__))

    import voxi_1  # noqa: E402

    voxi_1.main()


if __name__ == "__main__":
    main()
