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

### Whole-board image backup/restore over SSH

Use this flow when the UP 7000 is booted from a live USB and the internal eMMC must be backed up or restored from the host.

Assumptions:
- Target is reachable over SSH at `user@192.168.55.1`
- Password is `user`
- The live USB is the boot device (`/dev/sda` in the examples below)
- The internal board storage is `/dev/mmcblk0`
- `sudo -n true` works on the target
- Host has `sshpass`, `gzip`, and enough free disk space

Always verify the target disks before writing anything:

```bash
sshpass -p user ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
  user@192.168.55.1 \
  'lsblk -b -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINT'
```

Expected layout during live-USB imaging:
- `/dev/sda` is the live USB
- `/dev/mmcblk0` is the internal eMMC
- the eMMC boot areas are `/dev/mmcblk0boot0` and `/dev/mmcblk0boot1`

### Backup a full eMMC image

Create a backup directory on the host:

```bash
BACKUP_DIR=/media/ranshal/intel/up7000/backups/up7000-$(date +%Y%m%d)
mkdir -p "$BACKUP_DIR"
```

Save partition metadata:

```bash
sshpass -p user ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
  user@192.168.55.1 \
  'sudo sfdisk -d /dev/mmcblk0' > "$BACKUP_DIR/mmcblk0.sfdisk"
```

Back up the two eMMC boot partitions:

```bash
sshpass -p user ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
  user@192.168.55.1 \
  'sudo dd if=/dev/mmcblk0boot0 bs=1M status=none | gzip -1 -c' \
  > "$BACKUP_DIR/mmcblk0boot0.img.gz"

sshpass -p user ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
  user@192.168.55.1 \
  'sudo dd if=/dev/mmcblk0boot1 bs=1M status=none | gzip -1 -c' \
  > "$BACKUP_DIR/mmcblk0boot1.img.gz"
```

Back up the main eMMC user area:

```bash
sshpass -p user ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
  user@192.168.55.1 \
  'sudo dd if=/dev/mmcblk0 bs=16M iflag=fullblock status=none | gzip -1 -c' \
  > "$BACKUP_DIR/mmcblk0.img.gz"
```

Generate and verify checksums:

```bash
(cd "$BACKUP_DIR" && sha256sum *.gz > SHA256SUMS)
(cd "$BACKUP_DIR" && sha256sum -c SHA256SUMS)
gzip -t "$BACKUP_DIR"/*.gz
```

### Restore a full eMMC image

Warning: restore is destructive and overwrites the entire target eMMC and both boot partitions.

First, verify the replacement board exposes the expected eMMC target:

```bash
sshpass -p user ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
  user@192.168.55.1 \
  'sudo blockdev --getsize64 /dev/mmcblk0 && lsblk -b -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINT /dev/mmcblk0 /dev/mmcblk0boot0 /dev/mmcblk0boot1'
```

Restore the main eMMC image:

```bash
gzip -dc "$BACKUP_DIR/mmcblk0.img.gz" | \
  sshpass -p user ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
  user@192.168.55.1 \
  'sudo dd of=/dev/mmcblk0 bs=16M oflag=direct conv=fsync status=none'
```

Temporarily unlock the boot partitions, restore them, then lock them again:

```bash
sshpass -p user ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
  user@192.168.55.1 \
  'echo 0 | sudo tee /sys/block/mmcblk0boot0/force_ro >/dev/null && \
   echo 0 | sudo tee /sys/block/mmcblk0boot1/force_ro >/dev/null'

gzip -dc "$BACKUP_DIR/mmcblk0boot0.img.gz" | \
  sshpass -p user ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
  user@192.168.55.1 \
  'sudo dd of=/dev/mmcblk0boot0 bs=1M conv=fsync status=none'

gzip -dc "$BACKUP_DIR/mmcblk0boot1.img.gz" | \
  sshpass -p user ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
  user@192.168.55.1 \
  'sudo dd of=/dev/mmcblk0boot1 bs=1M conv=fsync status=none'

sshpass -p user ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
  user@192.168.55.1 \
  'echo 1 | sudo tee /sys/block/mmcblk0boot0/force_ro >/dev/null && \
   echo 1 | sudo tee /sys/block/mmcblk0boot1/force_ro >/dev/null && \
   sudo sync'
```

Sanity-check the restored partitions:

```bash
sshpass -p user ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
  user@192.168.55.1 \
  'sudo blkid /dev/mmcblk0p1 /dev/mmcblk0p2 /dev/mmcblk0p3; \
   cat /sys/block/mmcblk0boot0/force_ro; \
   cat /sys/block/mmcblk0boot1/force_ro'
```

After restore completes, reboot the board from internal storage.

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
- `~/fira-venv/bin/python device_code/aft`
- `~/fira-venv/bin/python device_code/camera.py voxi --camera-id 2 --gui`

### Voxi
~/fira-venv/bin/python device_code/voxi.py --gui

Serial-port selection:
- `--serial-device` is now optional.
- When `--camera-id` or `--video-device` selects a concrete `/dev/videoN`, the scripts first try to infer the matching `/dev/ttyUSB*` or `/dev/ttyACM*` from the shared USB branch in sysfs.
- Keep using `--serial-device` as an explicit override if the topology is unusual or multiple cameras are attached and auto-pairing is ambiguous.

Headless commands:
- In `--headless` mode there is no OpenCV window, so runtime commands are read from stdin instead of keyboard shortcuts.
- FIRA supported stdin commands: `v`, `n`, `r`, `a`, `A`, `+`, `-`, `esc`.
- VOXI supported stdin commands: `v`, `n`, `r`, `esc`.
- Example: `~/fira-venv/bin/python device_code/camera.py fira --camera-id 0 --headless`
  then type commands followed by Enter.

Troubleshooting:
- If you see `QFontDatabase: Cannot find font directory .../cv2/qt/fonts`: this is a Qt/OpenCV warning (often harmless). Installing `fontconfig` and `fonts-dejavu-core` on the target usually removes it.
- If the script prints `/dev/videoN is busy`, check who owns it with `fuser -v /dev/videoN` and stop that process.
- If you see repeated `Frame too small ... wrong /dev/video* node`, try running without `--camera-id` (auto-detect), or try the other `/dev/video*` nodes that belong to the VOXI device (`v4l2-ctl --list-devices`).
- If a CH341 serial port disappears on a Linux host with dmesg lines like `usbfs: interface 0 claimed by ch341 while 'brltty' sets config #1`, this is usually the host `brltty` service fighting the kernel `ch341` driver. Disable or remove `brltty` on the host (`sudo systemctl disable --now brltty` or uninstall the package), then unplug and reconnect the camera.


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

## degredeation in performance with 2 cameras
gui + without printing error
418
393

headless + without printing
489
490

gui + printinh
380
410

headless+printing
400
400


The root cause is USB bandwidth saturation on the current camera path, not the UP-7000 CPU, not disk write speed, and not a USB Ethernet adapter.

Here is the chain of evidence:

Both FIRA cameras are currently running as UVC devices on the same USB 2.0 High Speed bus at 480 Mbps.
Evidence from the target: lsusb -t showed both cameras under Bus 001 at 480M, on usb-0000:00:14.0-2.2 and usb-0000:00:14.0-3.2.
Each camera advertises uncompressed YUYV at 640x512 and 50 fps.
Evidence from the target: v4l2-ctl --list-formats-ext showed YUYV 4:2:2, 640x512, 0.020s (50.000 fps) for both video0 and /dev/video2.
That stream size is too large for two cameras on one 480 Mbps USB2 bus:
One camera: 
640
×
512
×
2
×
50
=
65,536,000
640×512×2×50=65,536,000 bytes/s
In bits: about 
524.3
524.3 Mbps for two cameras combined? Let's compute carefully:
One camera: 
65,536,000
 B/s
×
8
=
524,288,000
 b/s
65,536,000 B/s×8=524,288,000 b/s? No. The earlier bytes/s is already one camera at 50 fps: 
640
×
512
×
2
=
655,360
640×512×2=655,360 bytes/frame, times 50 = 
32,768,000
32,768,000 bytes/s.
One camera in bits: about 
262.1
262.1 Mbps.
Two cameras: about 
524.3
524.3 Mbps raw payload, before USB protocol overhead.
USB2 High Speed cannot carry that aggregate uncompressed load reliably, so the UVC driver occasionally delivers truncated frame payloads.
That truncated-payload symptom is exactly what your application is reporting. In fira_1.py:343, the warning is raised when the received frame buffer length is not divisible by the expected width. The bad sizes I observed on the target were slightly smaller than the expected full frame size, for example values corresponding to about 642536, 643192, 323112*2, etc. That pattern matches incomplete USB/UVC transfers, not a reshape bug and not a TIFF-writing bug.

I also ruled out the other candidates:

Not a USB network adapter limitation:
The active NIC is onboard PCIe Realtek r8169 on 0000:01:00.0, not USB.
Not an inherent UP-7000 platform limitation:
The board datasheet lists USB 3.2 Gen 2 ports. The problem is that the cameras are currently negotiated on a 480M USB2 path, likely through the actual hub/cable/topology being used.
Not primarily the recording code:
Recording makes the issue visible because the code only saves complete frames at fira_1.py:372. When the USB bus hands it a truncated frame, that frame is dropped and never written, so the saved frame count goes down. But the root event is upstream transport truncation.
What recording changes is visibility, not the underlying cause. During simultaneous recording, every truncated USB frame becomes one missing TIFF on disk, so users notice “400 instead of 500.” The Unexpected frame size warnings are the direct signal that the camera data is already corrupted before cv2.imwrite is called.

So the root cause is:

Two uncompressed 640x512 YUYV 50 fps camera streams are sharing a single 480 Mbps USB2 bus.
That oversubscribes available bandwidth.
The result is occasional truncated UVC frame payloads.
The application drops those truncated frames, so recorded frame counts fall below nominal.
The practical implication is also clear: if you move both cameras onto true USB 3.x paths, or split them across independent host controllers/buses, this degradation should largely disappear. If they remain on a shared 480M path, the warnings and frame loss are expected.

GPT-5.4 • 1x


sudo pkill -f '/bin/brltty|/sbin/brltty'
printf '3-6.3:1.0' | sudo tee /sys/bus/usb/drivers/ch341/bind
ls -l /dev/ttyUSB*

sudo pkill -f '/bin/brltty|/sbin/brltty'
lsusb -t
printf '3-6.3:1.0' | sudo tee /sys/bus/usb/drivers/ch341/bind
ls -l /dev/ttyUSB*

# Live USB
enable ssh:
sudo systemctl enable --now ssh
change user passwd:
sudo passwd user
