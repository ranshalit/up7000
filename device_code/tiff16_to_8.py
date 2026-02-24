#!/usr/bin/env python3

import argparse
from pathlib import Path
from typing import Literal, Optional, Tuple

import numpy as np

try:
    import cv2
except ModuleNotFoundError as e:
    raise SystemExit(
        "Missing Python module 'cv2' (OpenCV). Install it (e.g. 'sudo apt-get install python3-opencv') "
        "or run this script inside a virtualenv that has opencv-python installed."
    ) from e


Method = Literal["minmax", "shift", "clip", "percentile"]


def _parse_percent_pair(s: str) -> Tuple[float, float]:
    parts = [p.strip() for p in (s or "").split(",")]
    if len(parts) != 2:
        raise argparse.ArgumentTypeError("Expected two comma-separated values like '1,99'")
    try:
        lo = float(parts[0])
        hi = float(parts[1])
    except ValueError as e:
        raise argparse.ArgumentTypeError("Invalid percentile pair") from e
    if not (0.0 <= lo < hi <= 100.0):
        raise argparse.ArgumentTypeError("Percentiles must satisfy 0 <= lo < hi <= 100")
    return lo, hi


def _read_image(path: Path) -> np.ndarray:
    img = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if img is None:
        raise SystemExit(f"Failed to read image: {path}")
    return img


def _scale_to_u8(
    img: np.ndarray,
    *,
    method: Method,
    clip_min: Optional[int] = None,
    clip_max: Optional[int] = None,
    percent_lo: float = 1.0,
    percent_hi: float = 99.0,
) -> np.ndarray:
    if img.dtype == np.uint8:
        return img

    if img.dtype != np.uint16:
        raise SystemExit(f"Expected uint16 or uint8 input, got dtype={img.dtype}")

    if method == "shift":
        return (img >> 8).astype(np.uint8)

    if method == "clip":
        if clip_min is None or clip_max is None:
            raise SystemExit("--clip-min and --clip-max are required for --method clip")
        lo = int(clip_min)
        hi = int(clip_max)
        if not (0 <= lo < hi <= 65535):
            raise SystemExit("clip range must satisfy 0 <= clip-min < clip-max <= 65535")
        clipped = np.clip(img, lo, hi)
        out = ((clipped.astype(np.float32) - lo) * (255.0 / float(hi - lo))).round()
        return np.clip(out, 0, 255).astype(np.uint8)

    if method == "percentile":
        lo_p = float(percent_lo)
        hi_p = float(percent_hi)
        lo = float(np.percentile(img, lo_p))
        hi = float(np.percentile(img, hi_p))
        if not (hi > lo):
            return np.zeros_like(img, dtype=np.uint8)
        clipped = np.clip(img.astype(np.float32), lo, hi)
        out = ((clipped - lo) * (255.0 / (hi - lo))).round()
        return np.clip(out, 0, 255).astype(np.uint8)

    # method == "minmax"
    lo = int(img.min())
    hi = int(img.max())
    if hi <= lo:
        return np.zeros_like(img, dtype=np.uint8)
    out = ((img.astype(np.float32) - float(lo)) * (255.0 / float(hi - lo))).round()
    return np.clip(out, 0, 255).astype(np.uint8)


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Convert 16-bit TIFF (uint16) to 8-bit (uint8)")
    p.add_argument("input", type=Path, help="Input TIFF path")
    p.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Output image path (default: <input>_8bit.png)",
    )
    p.add_argument(
        "--method",
        choices=["minmax", "shift", "clip", "percentile"],
        default="minmax",
        help="Scaling method: minmax (default), shift (>>8), clip, percentile",
    )
    p.add_argument("--clip-min", type=int, default=None, help="For --method clip: minimum (0..65535)")
    p.add_argument("--clip-max", type=int, default=None, help="For --method clip: maximum (0..65535)")
    p.add_argument(
        "--percent",
        type=_parse_percent_pair,
        default=(1.0, 99.0),
        metavar="LO,HI",
        help="For --method percentile: percent range (default 1,99)",
    )
    return p.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> None:
    args = parse_args(argv)

    inp: Path = args.input
    if not inp.exists():
        raise SystemExit(f"Input not found: {inp}")

    out: Path
    if args.output is None:
        out = inp.with_name(inp.stem + "_8bit.png")
    else:
        out = args.output

    img16 = _read_image(inp)
    lo_p, hi_p = args.percent

    img8 = _scale_to_u8(
        img16,
        method=args.method,
        clip_min=args.clip_min,
        clip_max=args.clip_max,
        percent_lo=lo_p,
        percent_hi=hi_p,
    )

    out.parent.mkdir(parents=True, exist_ok=True)
    ok = cv2.imwrite(str(out), img8)
    if not ok:
        raise SystemExit(f"Failed to write output: {out}")

    print(f"Wrote: {out}")


if __name__ == "__main__":
    main()
