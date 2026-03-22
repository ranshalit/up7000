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

### Generic Wrapper
~/fira-venv/bin/python device_code/camera.py voxi --gui

The first argument selects the backend wrapper:
- `fira`
- `voxi`

All remaining arguments are forwarded unchanged to the selected backend.

Examples:
- `~/fira-venv/bin/python device_code/camera.py fira --camera-id 0 --gui`
- `~/fira-venv/bin/python device_code/camera.py voxi --camera-id 2 --gui`

### Voxi
~/fira-venv/bin/python device_code/voxi.py --gui

Serial-port selection:
- `--serial-device` is now optional.
- When `--camera-id` or `--video-device` selects a concrete `/dev/videoN`, the scripts first try to infer the matching `/dev/ttyUSB*` or `/dev/ttyACM*` from the shared USB branch in sysfs.
- Keep using `--serial-device` as an explicit override if the topology is unusual or multiple cameras are attached and auto-pairing is ambiguous.

Troubleshooting:
- If you see `QFontDatabase: Cannot find font directory .../cv2/qt/fonts`: this is a Qt/OpenCV warning (often harmless). Installing `fontconfig` and `fonts-dejavu-core` on the target usually removes it.
- If the script prints `/dev/videoN is busy`, check who owns it with `fuser -v /dev/videoN` and stop that process.
- If you see repeated `Frame too small ... wrong /dev/video* node`, try running without `--camera-id` (auto-detect), or try the other `/dev/video*` nodes that belong to the VOXI device (`v4l2-ctl --list-devices`).


### install
UP7000 was installed with ubuntu 24.4 (tough official docs speak of ubuntu 22.2)
installed using hdmi connected
configured with ip 192.168.55.1 and with login: ubuntu, password: ubuntu

# Usage
connect with ssh -X ubuntu@192.168.55.1
(pwd: ubuntu)
then you can start running camera video capture:
Currently, 2 cameras are supported:
FIRA - idVendor=1a86, idProduct=7523, 
VOXI - idVendor=0c45, idProduct=636b

when connecting a camera you need to check 2 things:
1. Which camera device ID is used with the new camera ( /dev/video#X ) , you can easily know if dmesg is opened
with dmesg -wHT and then you connect the camera

When connecting a single camera, you will actually see 2 devices e.g. 
   /dev/video0, /dev/video1 , so in this case camera ID is 0
Note: previously serial device was also an argument but it was removed for easier usage (it is still an optional input to override the autodetection --serial-device /dev/ttyUSB0 )
Generic wrapper:
python camera.py voxi --camera-id <camera ID> --gui
python camera.py fira --camera-id <camera ID> --gui
e.g.
python camera.py fira --camera-id 2 --gui
python camera.py voxi --camera-id 3 --gui

Actually we see that the 2 scripts are basically generic except for few commands difference, so we better change it to use generic camera scrypt

NOTE: if you connect multiple cameras to device you will probably see in serial messeges such as:
...
Unexpected frame size: 327288 uint16 values (width=640)
10.400429248809814
...
So there is obvious degredation in performance.

# TODO

use generic camera scrypt with 2 difference backend devices and auto camera detection