import re
from pathlib import Path
from typing import Iterable


_USB_DEVICE_RE = re.compile(r"^\d+-\d+(?:\.\d+)*$")
_VIDEO_DEVICE_RE = re.compile(r"^video\d+$")
_SERIAL_PREFIXES = ("ttyUSB", "ttyACM")


def _usb_ancestor_chain(sysfs_path: Path) -> list[str]:
    tokens: list[str] = []
    for part in sysfs_path.parts:
        token = part.split(":", 1)[0]
        if _USB_DEVICE_RE.fullmatch(token):
            if not tokens or tokens[-1] != token:
                tokens.append(token)

    if not tokens:
        return []

    chain: list[str] = []
    current = tokens[-1]
    while True:
        chain.append(current)
        if "." not in current:
            break
        current = current.rsplit(".", 1)[0]
    return chain


def _video_sysfs_device(video_device: str) -> Path | None:
    name = Path(video_device).name
    if not _VIDEO_DEVICE_RE.fullmatch(name):
        return None
    try:
        return (Path("/sys/class/video4linux") / name / "device").resolve(strict=True)
    except FileNotFoundError:
        return None


def _serial_port_chains() -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    tty_root = Path("/sys/class/tty")
    if not tty_root.exists():
        return result

    for tty_dir in sorted(tty_root.iterdir()):
        name = tty_dir.name
        if not name.startswith(_SERIAL_PREFIXES):
            continue
        try:
            sysfs_path = (tty_dir / "device").resolve(strict=True)
        except FileNotFoundError:
            continue
        chain = _usb_ancestor_chain(sysfs_path)
        if chain:
            result[f"/dev/{name}"] = chain
    return result


def infer_serial_port_for_video_device(video_device: str) -> str | None:
    video_sysfs = _video_sysfs_device(video_device)
    if video_sysfs is None:
        return None

    video_chain = _usb_ancestor_chain(video_sysfs)
    if not video_chain:
        return None

    matches: list[tuple[tuple[int, int, int], str]] = []
    for port, tty_chain in _serial_port_chains().items():
        best_rank: tuple[int, int, int] | None = None
        for video_depth, segment in enumerate(video_chain):
            if segment not in tty_chain:
                continue
            tty_depth = tty_chain.index(segment)
            rank = (segment.count("."), -video_depth, -tty_depth)
            if best_rank is None or rank > best_rank:
                best_rank = rank
        if best_rank is not None:
            matches.append((best_rank, port))

    if not matches:
        return None

    matches.sort(key=lambda item: (item[0], item[1]), reverse=True)
    best_rank = matches[0][0]
    best_ports = sorted(port for rank, port in matches if rank == best_rank)
    if len(best_ports) != 1:
        return None
    return best_ports[0]


def infer_serial_port_for_video_id(video_id: int) -> str | None:
    return infer_serial_port_for_video_device(f"/dev/video{int(video_id)}")


def infer_serial_port_for_video_ids(video_ids: Iterable[int]) -> dict[int, str]:
    result: dict[int, str] = {}
    for video_id in video_ids:
        port = infer_serial_port_for_video_id(int(video_id))
        if port:
            result[int(video_id)] = port
    return result