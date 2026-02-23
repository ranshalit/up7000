# Disk backup/restore (partition table + partclone)

This workspace includes a helper script for imaging a whole block device by:
- backing up the partition table, and
- running the correct `partclone.*` binary per partition filesystem type.

## Prerequisites (host)

- Run as root (`sudo`).
- Tools: `lsblk`, `sfdisk`, `blkid` (optional but recommended), `partprobe` (recommended), `partclone`.
- If the device uses GPT: `sgdisk` is recommended (script will still save a `sfdisk --dump` fallback).

On Ubuntu/Debian, the packages are typically:
- `partclone`
- `gdisk` (for `sgdisk`)

## Backup

```bash
sudo python3 device_code/disk_backup_restore.py backup \
  --device /dev/sda \
  --outdir /mnt/backup/sda
```

Artifacts written into `--outdir`:
- `backup.json`
- `partition-table.sfdisk`
- `partition-table.gpt.bin` (only for GPT when `sgdisk` exists)
- `images/partXX-<name>-<fstype>.img`

## Restore

```bash
sudo python3 device_code/disk_backup_restore.py restore \
  --device /dev/sda \
  --indir /mnt/backup/sda \
  --yes
```

Notes:
- Restore overwrites the target device partition table and partition contents.
- If the target disk is smaller than the source disk size in the backup metadata, restore aborts.

## Options

- `--umount`: attempt to unmount mounted partitions before imaging/restoring.
- `--skip-unsupported`: skip partitions whose filesystem type is not supported by the built-in partclone mapping.
- `--fallback-dd`: use `dd` for partitions with unknown filesystem types (both backup + restore must use it).
- `--ignore-fschk`: pass `-I/--ignore_fschk` to `partclone` (useful if a filesystem is marked unclean; may risk inconsistency).
- `--dry-run`: print commands without executing.
