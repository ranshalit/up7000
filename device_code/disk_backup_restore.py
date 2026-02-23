#!/usr/bin/env python3
"""Backup/restore a whole block device using partition-table backup + partclone images.

This script is intentionally conservative:
- Requires root.
- Refuses restore unless --yes or interactive confirmation.
- Attempts to unmount mounted partitions (optional).

Backup artifacts (outdir):
- backup.json (metadata)
- partition-table.sfdisk (sfdisk --dump)
- partition-table.gpt.bin (sgdisk --backup, only when GPT + sgdisk present)
- images/<partition>.img (partclone images)

Typical usage:
  sudo ./disk_backup_restore.py backup  --device /dev/sda --outdir /mnt/backup/sda
  sudo ./disk_backup_restore.py restore --device /dev/sda --indir  /mnt/backup/sda --yes
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple


@dataclass(frozen=True)
class PartitionInfo:
    number: int
    path: str
    name: str
    fstype: str
    uuid: str
    partuuid: str
    label: str
    partlabel: str


_PARTCLONE_BY_FSTYPE: Dict[str, str] = {
    # ext2/3/4 (partclone.extfs supports ext2/3/4)
    "ext2": "partclone.extfs",
    "ext3": "partclone.extfs",
    "ext4": "partclone.extfs",
    "xfs": "partclone.xfs",
    "btrfs": "partclone.btrfs",
    "ntfs": "partclone.ntfs",
    "vfat": "partclone.fat",
    "fat": "partclone.fat",
    "fat32": "partclone.fat",
    "f2fs": "partclone.f2fs",
    "reiserfs": "partclone.reiserfs",
    "hfsplus": "partclone.hfsplus",
    "swap": "partclone.swap",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _eprint(msg: str) -> None:
    print(msg, file=sys.stderr)


def _require_root(*, dry_run: bool) -> None:
    if dry_run:
        return
    if os.geteuid() != 0:
        raise SystemExit("This script must be run as root (use sudo).")


def _is_block_device(path: str) -> bool:
    try:
        st = os.stat(path)
    except FileNotFoundError:
        return False
    return stat.S_ISBLK(st.st_mode)


def _which(cmd: str) -> Optional[str]:
    return shutil.which(cmd)


def _run(
    argv: Sequence[str],
    *,
    input_text: Optional[str] = None,
    check: bool = True,
    capture: bool = True,
    dry_run: bool = False,
) -> subprocess.CompletedProcess[str]:
    if dry_run:
        _eprint("DRY-RUN: " + " ".join(shlex.quote(a) for a in argv))
        return subprocess.CompletedProcess(list(argv), 0, stdout="", stderr="")

    return subprocess.run(
        list(argv),
        input=input_text,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        check=check,
    )


def _lsblk_json(device: str, *, dry_run: bool) -> Dict[str, Any]:
    cp = _run(["lsblk", "-J", "-O", device], dry_run=dry_run)
    if dry_run:
        return {}
    return json.loads(cp.stdout or "{}")


def _device_pttype(device: str, *, dry_run: bool) -> str:
    # values: gpt, dos, loop, ...
    cp = _run(["lsblk", "-dn", "-o", "PTTYPE", device], dry_run=dry_run)
    return (cp.stdout or "").strip() if not dry_run else ""


def _device_size_bytes(device: str, *, dry_run: bool) -> int:
    cp = _run(["lsblk", "-dn", "-b", "-o", "SIZE", device], dry_run=dry_run)
    if dry_run:
        return 0
    s = (cp.stdout or "").strip()
    return int(s) if s.isdigit() else 0


def _partition_path_for_number(device: str, number: int) -> str:
    # /dev/sda -> /dev/sda1
    # /dev/nvme0n1 -> /dev/nvme0n1p1
    # /dev/mmcblk0 -> /dev/mmcblk0p1
    suffix = "p" if re.search(r"\d$", device) else ""
    return f"{device}{suffix}{number}"


def _list_partitions(device: str, *, dry_run: bool) -> List[PartitionInfo]:
    # Use lsblk for structure, blkid for UUID/LABEL.
    # NAME is without /dev/, but we prefer PATH.
    cols = "NAME,PATH,TYPE,FSTYPE,PARTN,MOUNTPOINT"
    cp = _run(["lsblk", "-nr", "-o", cols, device], dry_run=dry_run)
    if dry_run:
        return []

    parts: List[PartitionInfo] = []
    for line in (cp.stdout or "").splitlines():
        # Example: sda1 /dev/sda1 part ext4 1 /mnt
        # Some fields can be empty -> lsblk still prints separators; with -n -r it is space-separated.
        fields = line.split(None, 5)
        if len(fields) < 4:
            continue
        name, path, typ, fstype = fields[0:4]
        partn = fields[4] if len(fields) >= 5 else ""
        if typ != "part":
            continue
        try:
            number = int(partn)
        except Exception:
            # Fallback: parse trailing digits from partition name.
            m = re.search(r"(\d+)$", name)
            if not m:
                continue
            number = int(m.group(1))

        uuid, label, partuuid, partlabel = _blkid_attrs(path, dry_run=dry_run)
        parts.append(
            PartitionInfo(
                number=number,
                path=path,
                name=name,
                fstype=(fstype or "").strip(),
                uuid=uuid,
                partuuid=partuuid,
                label=label,
                partlabel=partlabel,
            )
        )

    parts.sort(key=lambda p: p.number)
    return parts


def _blkid_attrs(devpath: str, *, dry_run: bool) -> Tuple[str, str, str, str]:
    # Return: UUID, LABEL, PARTUUID, PARTLABEL
    if _which("blkid") is None:
        return ("", "", "", "")

    cp = _run(["blkid", "-o", "export", devpath], check=False, dry_run=dry_run)
    if dry_run:
        return ("", "", "", "")

    uuid = label = partuuid = partlabel = ""
    for line in (cp.stdout or "").splitlines():
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        if k == "UUID":
            uuid = v
        elif k == "LABEL":
            label = v
        elif k == "PARTUUID":
            partuuid = v
        elif k == "PARTLABEL":
            partlabel = v
    return (uuid, label, partuuid, partlabel)


def _mounted_partitions(device: str, *, dry_run: bool) -> List[Tuple[str, str]]:
    # Returns list of (path, mountpoint)
    cp = _run(["lsblk", "-nr", "-o", "PATH,MOUNTPOINT", device], dry_run=dry_run)
    if dry_run:
        return []

    mounted: List[Tuple[str, str]] = []
    for line in (cp.stdout or "").splitlines():
        fields = line.split(None, 1)
        if not fields:
            continue
        path = fields[0]
        mountpoint = fields[1].strip() if len(fields) > 1 else ""
        if mountpoint:
            mounted.append((path, mountpoint))
    return mounted


def _try_unmount_all(device: str, *, dry_run: bool) -> None:
    mounted = _mounted_partitions(device, dry_run=dry_run)
    if not mounted:
        return

    if _which("umount") is None:
        raise SystemExit("Found mounted partitions but 'umount' is not available.")

    # Unmount deepest mountpoints first
    mounted_sorted = sorted(mounted, key=lambda t: len(t[1]), reverse=True)
    for path, mountpoint in mounted_sorted:
        _eprint(f"Unmounting {path} from {mountpoint} ...")
        _run(["umount", path], dry_run=dry_run)


def _backup_partition_table(device: str, outdir: Path, pttype: str, *, dry_run: bool) -> Dict[str, str]:
    out: Dict[str, str] = {}

    sfdisk_path = outdir / "partition-table.sfdisk"
    if _which("sfdisk") is None:
        raise SystemExit("Missing required tool: sfdisk")

    cp = _run(["sfdisk", "--dump", device], dry_run=dry_run)
    if not dry_run:
        sfdisk_path.write_text(cp.stdout or "", encoding="utf-8")
    out["sfdisk_dump"] = str(sfdisk_path)

    if pttype == "gpt" and _which("sgdisk") is not None:
        gpt_path = outdir / "partition-table.gpt.bin"
        _run(["sgdisk", f"--backup={gpt_path}", device], dry_run=dry_run)
        out["sgdisk_backup"] = str(gpt_path)

    return out


def _restore_partition_table(device: str, indir: Path, meta: Dict[str, Any], *, dry_run: bool) -> None:
    pttype = str(meta.get("pttype") or "").strip()

    # Prefer GPT binary backup if available.
    gpt_bin = meta.get("partition_table", {}).get("sgdisk_backup")
    if pttype == "gpt" and gpt_bin and _which("sgdisk") is not None:
        gpt_path = Path(gpt_bin)
        if not gpt_path.is_absolute():
            gpt_path = indir / gpt_path

        if not gpt_path.exists() and not dry_run:
            raise SystemExit(f"Missing GPT partition-table backup: {gpt_path}")

        _eprint("Restoring GPT partition table using sgdisk...")
        _run(["sgdisk", "--zap-all", device], dry_run=dry_run)
        _run(["sgdisk", f"--load-backup={gpt_path}", device], dry_run=dry_run)
        _partprobe(device, dry_run=dry_run)
        return

    # Fallback to sfdisk dump
    sfdisk_dump = meta.get("partition_table", {}).get("sfdisk_dump") or "partition-table.sfdisk"
    sfdisk_path = Path(str(sfdisk_dump))
    if not sfdisk_path.is_absolute():
        sfdisk_path = indir / sfdisk_path

    if _which("sfdisk") is None:
        raise SystemExit("Missing required tool: sfdisk")
    if not sfdisk_path.exists() and not dry_run:
        raise SystemExit(f"Missing sfdisk dump file: {sfdisk_path}")

    _eprint("Restoring partition table using sfdisk...")
    input_text = "" if dry_run else sfdisk_path.read_text(encoding="utf-8")
    _run(["sfdisk", "--force", device], input_text=input_text, dry_run=dry_run)
    _partprobe(device, dry_run=dry_run)


def _partprobe(device: str, *, dry_run: bool) -> None:
    if _which("partprobe") is not None:
        _run(["partprobe", device], check=False, dry_run=dry_run)
    if _which("udevadm") is not None:
        _run(["udevadm", "settle"], check=False, dry_run=dry_run)


def _partclone_cmd_for_fstype(fstype: str) -> Optional[str]:
    ft = (fstype or "").strip().lower()
    if not ft:
        return None
    return _PARTCLONE_BY_FSTYPE.get(ft)


def _confirm_dangerous(action: str, device: str, *, assume_yes: bool) -> None:
    if assume_yes:
        return

    _eprint("")
    _eprint("DANGEROUS OPERATION")
    _eprint(f"Action: {action}")
    _eprint(f"Target device: {device}")
    _eprint("This will overwrite the partition table and filesystem data on the target device.")
    resp = input("Type 'YES' to continue: ").strip()
    if resp != "YES":
        raise SystemExit("Aborted by user.")


def _ensure_tools_or_die(mode: str, *, dry_run: bool) -> None:
    required = ["lsblk", "sfdisk"]
    if mode in {"backup", "restore"}:
        required.append("partclone.extfs")  # sanity check that partclone is installed at all

    missing = [t for t in required if _which(t) is None]
    if missing and not dry_run:
        raise SystemExit("Missing required tools: " + ", ".join(missing))
    if missing and dry_run:
        _eprint("DRY-RUN: missing tools would fail in a real run: " + ", ".join(missing))


def _backup(
    *,
    device: str,
    outdir: Path,
    umount: bool,
    skip_unsupported: bool,
    fallback_dd: bool,
    ignore_fschk: bool,
    resume: bool,
    dry_run: bool,
) -> None:
    _require_root(dry_run=dry_run)
    _ensure_tools_or_die("backup", dry_run=dry_run)

    if not dry_run and not _is_block_device(device):
        raise SystemExit(f"Not a block device: {device}")

    outdir.mkdir(parents=True, exist_ok=True)
    images_dir = outdir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    if umount:
        _try_unmount_all(device, dry_run=dry_run)

    pttype = _device_pttype(device, dry_run=dry_run)
    dev_size = _device_size_bytes(device, dry_run=dry_run)

    part_table = _backup_partition_table(device, outdir, pttype, dry_run=dry_run)

    lsblk_info = _lsblk_json(device, dry_run=dry_run)
    if not dry_run:
        (outdir / "lsblk.json").write_text(json.dumps(lsblk_info, indent=2), encoding="utf-8")

    parts = _list_partitions(device, dry_run=dry_run)
    if not parts and not dry_run:
        raise SystemExit(f"No partitions found on {device}")

    meta: Dict[str, Any] = {
        "created_at": _now_iso(),
        "device": device,
        "device_size_bytes": dev_size,
        "pttype": pttype,
        "partition_table": {
            # store as relative paths when possible
            "sfdisk_dump": os.path.relpath(part_table.get("sfdisk_dump", ""), outdir),
        },
        "partitions": [],
    }
    if "sgdisk_backup" in part_table:
        meta["partition_table"]["sgdisk_backup"] = os.path.relpath(part_table["sgdisk_backup"], outdir)

    _eprint(f"Found {len(parts)} partitions on {device}. Starting partclone backup...")

    for p in parts:
        fstype = (p.fstype or "").strip().lower()
        partclone = _partclone_cmd_for_fstype(fstype)

        image_name = f"part{p.number:02d}-{p.name}-{(fstype or 'unknown')}.img"
        image_path = images_dir / image_name

        entry: Dict[str, Any] = {
            "number": p.number,
            "name": p.name,
            "path": p.path,
            "fstype": fstype,
            "uuid": p.uuid,
            "partuuid": p.partuuid,
            "label": p.label,
            "partlabel": p.partlabel,
            "image": os.path.relpath(image_path, outdir),
            "method": "partclone" if partclone else ("dd" if fallback_dd else "skip"),
            "partclone": partclone or "",
        }

        if partclone:
            if _which(partclone) is None:
                msg = f"Missing tool for fstype '{fstype}': {partclone} (partition {p.path})"
                if skip_unsupported:
                    _eprint("WARN: " + msg + "; skipping")
                    entry["method"] = "skip"
                    meta["partitions"].append(entry)
                    continue
                raise SystemExit(msg)

            _eprint(f"Cloning {p.path} ({fstype}) -> {image_path.name}")
            if resume and image_path.exists() and (dry_run or image_path.stat().st_size > 0):
                _eprint(f"Skipping existing image (resume): {image_path.name}")
            else:
                if resume and image_path.exists() and not dry_run and image_path.stat().st_size == 0:
                    # partclone with -o will refuse to overwrite; remove empty partial.
                    image_path.unlink(missing_ok=True)

                argv = [partclone, "-c"]
                if ignore_fschk:
                    argv.append("-I")
                argv += ["-s", p.path, "-o", str(image_path)]
                _run(argv, dry_run=dry_run)
            entry["method"] = "partclone"

        elif fallback_dd:
            if _which("dd") is None:
                raise SystemExit("fallback-dd requested but 'dd' is not available")
            _eprint(f"Cloning {p.path} (unknown fstype) using dd -> {image_path.name}")
            # Use a reasonable default block size.
            _run(
                [
                    "dd",
                    f"if={p.path}",
                    f"of={image_path}",
                    "bs=16M",
                    "status=progress",
                    "conv=fsync",
                ],
                dry_run=dry_run,
            )
            entry["method"] = "dd"

        else:
            msg = f"Unsupported/unknown fstype for {p.path} (fstype='{fstype}')"
            if skip_unsupported:
                _eprint("WARN: " + msg + "; skipping")
                entry["method"] = "skip"
            else:
                raise SystemExit(msg + ". Use --skip-unsupported or --fallback-dd.")

        meta["partitions"].append(entry)

    if not dry_run:
        (outdir / "backup.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    _eprint(f"Backup complete: {outdir}")


def _wait_for_partition_nodes(device: str, numbers: List[int], timeout_s: int, *, dry_run: bool) -> None:
    if dry_run:
        return

    deadline = time.time() + timeout_s
    missing: List[int] = []
    while time.time() < deadline:
        missing = [n for n in numbers if not Path(_partition_path_for_number(device, n)).exists()]
        if not missing:
            return
        time.sleep(0.25)
    raise SystemExit(f"Timed out waiting for partition nodes on {device}: {missing}")


def _restore(
    *,
    device: str,
    indir: Path,
    assume_yes: bool,
    umount: bool,
    skip_unsupported: bool,
    fallback_dd: bool,
    dry_run: bool,
) -> None:
    _require_root(dry_run=dry_run)
    _ensure_tools_or_die("restore", dry_run=dry_run)

    if not dry_run and not _is_block_device(device):
        raise SystemExit(f"Not a block device: {device}")
    if not indir.is_dir():
        raise SystemExit(f"Backup directory not found: {indir}")

    meta_path = indir / "backup.json"
    if not meta_path.exists() and not dry_run:
        raise SystemExit(f"Missing metadata file: {meta_path}")

    meta: Dict[str, Any] = {} if dry_run else json.loads(meta_path.read_text(encoding="utf-8"))

    expected_size = int(meta.get("device_size_bytes") or 0)
    current_size = _device_size_bytes(device, dry_run=dry_run)
    if not dry_run and expected_size and current_size and current_size < expected_size:
        raise SystemExit(
            f"Target device ({device}) is smaller than the source backup: {current_size} < {expected_size} bytes"
        )

    if umount:
        _try_unmount_all(device, dry_run=dry_run)

    _confirm_dangerous("restore", device, assume_yes=assume_yes)

    _restore_partition_table(device, indir, meta, dry_run=dry_run)

    partitions = list(meta.get("partitions") or [])
    if not partitions and not dry_run:
        raise SystemExit("No partitions listed in backup.json")

    numbers = [int(p.get("number")) for p in partitions if str(p.get("method")) != "skip"]
    _wait_for_partition_nodes(device, numbers, timeout_s=15, dry_run=dry_run)

    _eprint(f"Restoring {len(numbers)} partitions to {device}...")

    for p in partitions:
        number = int(p.get("number"))
        method = str(p.get("method") or "")
        fstype = str(p.get("fstype") or "").lower()
        rel_image = str(p.get("image") or "")
        image_path = (indir / rel_image) if rel_image else None
        target_part = _partition_path_for_number(device, number)

        if method == "skip":
            _eprint(f"Skipping partition {number} ({fstype})")
            continue

        if not dry_run and (image_path is None or not image_path.exists()):
            raise SystemExit(f"Missing image for partition {number}: {image_path}")

        if method == "partclone":
            partclone = str(p.get("partclone") or "")
            if not partclone:
                partclone = _partclone_cmd_for_fstype(fstype) or ""

            if not partclone:
                msg = f"No partclone tool recorded for partition {number} (fstype='{fstype}')"
                if skip_unsupported:
                    _eprint("WARN: " + msg + "; skipping")
                    continue
                raise SystemExit(msg)

            if _which(partclone) is None:
                msg = f"Missing tool: {partclone} (partition {number}, fstype='{fstype}')"
                if skip_unsupported:
                    _eprint("WARN: " + msg + "; skipping")
                    continue
                raise SystemExit(msg)

            _eprint(f"Restoring {target_part} ({fstype}) from {image_path.name}")
            _run([partclone, "-r", "-s", str(image_path), "-o", target_part], dry_run=dry_run)

        elif method == "dd":
            if not fallback_dd:
                raise SystemExit(
                    f"Backup used dd for partition {number}, but restore did not allow dd. Use --fallback-dd."
                )
            if _which("dd") is None:
                raise SystemExit("'dd' is not available")
            _eprint(f"Restoring {target_part} (raw) from {image_path.name} using dd")
            _run(
                [
                    "dd",
                    f"if={image_path}",
                    f"of={target_part}",
                    "bs=16M",
                    "status=progress",
                    "conv=fsync",
                ],
                dry_run=dry_run,
            )
        else:
            raise SystemExit(f"Unknown method '{method}' for partition {number}")

    _run(["sync"], check=False, dry_run=dry_run)
    _eprint("Restore complete.")


def _parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Backup/restore partition table + partclone images for a block device")

    sub = p.add_subparsers(dest="mode", required=True)

    def add_common_flags(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--device", required=True, help="Block device (e.g. /dev/sda, /dev/nvme0n1)")
        sp.add_argument("--umount", action="store_true", help="Attempt to unmount any mounted partitions")
        sp.add_argument(
            "--skip-unsupported",
            action="store_true",
            help="Skip partitions whose filesystem type has no matching partclone tool",
        )
        sp.add_argument(
            "--fallback-dd",
            action="store_true",
            help="Use dd for partitions with unknown/unsupported filesystem types",
        )
        sp.add_argument(
            "--ignore-fschk",
            action="store_true",
            help="Pass -I/--ignore_fschk to partclone (useful for dirty/unclean filesystems; may risk inconsistency)",
        )
        sp.add_argument("--dry-run", action="store_true", help="Print commands but do not execute")

    sp_b = sub.add_parser("backup", help="Backup partition table and partclone all partitions")
    add_common_flags(sp_b)
    sp_b.add_argument(
        "--outdir",
        required=True,
        help="Output directory to write backup artifacts",
    )
    sp_b.add_argument(
        "--resume",
        action="store_true",
        help="If images already exist in outdir, skip recloning them and (re)write backup.json",
    )

    sp_r = sub.add_parser("restore", help="Restore partition table and partclone images back to the device")
    add_common_flags(sp_r)
    sp_r.add_argument(
        "--indir",
        required=True,
        help="Input directory created by the 'backup' command",
    )
    sp_r.add_argument("--yes", action="store_true", help="Do not prompt for confirmation")

    return p.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parse_args(argv)

    device = str(args.device).strip()
    if not device.startswith("/dev/"):
        raise SystemExit("--device must be a /dev/... path")

    if args.mode == "backup":
        _backup(
            device=device,
            outdir=Path(str(args.outdir)).expanduser(),
            umount=bool(args.umount),
            skip_unsupported=bool(args.skip_unsupported),
            fallback_dd=bool(args.fallback_dd),
            ignore_fschk=bool(args.ignore_fschk),
            resume=bool(args.resume),
            dry_run=bool(args.dry_run),
        )
        return 0

    if args.mode == "restore":
        _restore(
            device=device,
            indir=Path(str(args.indir)).expanduser(),
            assume_yes=bool(args.yes),
            umount=bool(args.umount),
            skip_unsupported=bool(args.skip_unsupported),
            fallback_dd=bool(args.fallback_dd),
            dry_run=bool(args.dry_run),
        )
        return 0

    raise SystemExit(f"Unknown mode: {args.mode}")


if __name__ == "__main__":
    raise SystemExit(main())
