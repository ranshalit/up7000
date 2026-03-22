import argparse
import importlib
import os
import sys
from typing import List, Optional


def parse_args(argv: List[str]) -> tuple[argparse.Namespace, List[str]]:
    parser = argparse.ArgumentParser(
        description="Generic camera wrapper that dispatches to the FIRA or VOXI wrapper.",
        epilog=(
            "Examples:\n"
            "  python camera.py fira --camera-id 0 --gui\n"
            "  python camera.py voxi --camera-id 2 --serial-device /dev/ttyUSB1 --gui"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "camera_type",
        choices=("fira", "voxi"),
        help="Which backend wrapper to run.",
    )
    return parser.parse_known_args(argv)


def main(argv: Optional[List[str]] = None) -> None:
    args, backend_argv = parse_args(list(sys.argv[1:] if argv is None else argv))

    sys.path.insert(0, os.path.dirname(__file__))
    module = importlib.import_module(args.camera_type)
    module.main(backend_argv)


if __name__ == "__main__":
    main()