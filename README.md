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


### install
UP7000 was installed with ubuntu 24.4 (tough official docs speak of ubuntu 22.2)
installed using hdmi connected
configured with ip 192.168.55.1 and with login: ubuntu, password: ubuntu

### Cameras
2 cameras are supported:
fira and voxi
when connecting a camera you need to check 2 things:
1. Which camera device ID is used with the new camera ( /dev/video#X ) ?
2. Which serial device ID is used with the new camera 
   ( /dev/ttyACM#Y - for voxi, 
     /dev/ttyUSB#Z - for fira ) ?
Note: When connecting a single camera, you will actually see 2 devices e.g. 
   /dev/video0, /dev/video1 , so in this case camera ID is 0

for voxi:
python voxi.py --camera-id <camera ID> --serial-device <serial device> --gui
python voxi.py --camera-id <camera ID> --serial-device <serial device> --gui
e.g.:
python voxi.py --camera-id 0 --serial-device /dev/ttyACM0 --gui
python fira.py --camera-id 1 --serial-device /dev/ttyUSB0 --gui
