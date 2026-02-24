# General
This is intel up 7000 device
https://up-board.org/up-7000/

## Workspace operating defaults
- Device defaults used by workspace skills and automation:
  - `target_ip`: `192.168.55.1`
  - `target_user`: `ubuntu`
  - `target_password`: `ubuntu`
  - `target_serial_device`: `/dev/ttyACM0`
  - `target_prompt_regex`: `(?:<username>@<username>:.*[$#]|[$#]) ?$`
- Per top-level `README.md`, current device-side workflow often uses `.github/skills/terminal-command-inject` and `.github/skills/scp-file-copy`.

## Disk backup/restore

- Script: `device_code/disk_backup_restore.py`
- Docs: `docs/disk-backup-restore.md`

# Usage
## Python venv note
`source ~/fira-venv/bin/activate` is not done automatically on boot because venv activation only affects the current shell session.

To avoid needing to source after a reset, run the scripts with the venv interpreter explicitly, or use the wrappers which re-exec into `~/fira-venv` when available.

## Run

### Voxi
~/fira-venv/bin/python device_code/voxi.py --serial-device /dev/ttyACM0 --gui

Troubleshooting:
- If you see `QFontDatabase: Cannot find font directory .../cv2/qt/fonts`: this is a Qt/OpenCV warning (often harmless). Installing `fontconfig` and `fonts-dejavu-core` on the target usually removes it.
- If the script prints `/dev/videoN is busy`, check who owns it with `fuser -v /dev/videoN` and stop that process.
- If you see repeated `Frame too small ... wrong /dev/video* node`, try running without `--camera-id` (auto-detect), or try the other `/dev/video*` nodes that belong to the VOXI device (`v4l2-ctl --list-devices`).

### Fira
~/fira-venv/bin/python device_code/fira.py --camera-id 0 --serial-device /dev/ttyUSB0 --gui