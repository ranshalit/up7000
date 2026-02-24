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
~/fira-venv/bin/python device_code/voxi.py --camera-id 0 --serial-device /dev/ttyACM0 --gui

### Fira
~/fira-venv/bin/python device_code/fira.py --camera-id 0 --serial-device /dev/ttyUSB0 --gui