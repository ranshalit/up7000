import shutil
import serial
import numpy as np
from linuxpy.video.device import Device
import cv2
import threading
import time
import os
import glob
from pathlib import Path
from datetime import datetime

CAMERA_PORT = os.environ.get("FIRA_CAMERA_PORT", "/dev/ttyUSB0")
CAMERA_BAUD = int(os.environ.get("FIRA_CAMERA_BAUD", "115200"))


def _get_env_int(*names: str, default: int) -> int:
    for name in names:
        raw = (os.environ.get(name) or "").strip()
        if raw != "":
            return int(raw)
    return int(default)


def _default_home_dir() -> Path:
    sudo_user = (os.environ.get("SUDO_USER") or "").strip()
    if os.geteuid() == 0 and sudo_user:
        candidate = Path("/home") / sudo_user
        if candidate.is_dir():
            return candidate
    return Path.home()


def _pick_camera_id(explicit: str) -> int:
    if explicit.strip() != "":
        return int(explicit)

    candidates = []
    for p in glob.glob("/dev/video[0-9]*"):
        base = os.path.basename(p)
        try:
            candidates.append(int(base.replace("video", "")))
        except ValueError:
            pass
    if not candidates:
        # Keep the old default as a last resort.
        return 2
    return min(candidates)


CAMERA_ID = _get_env_int("FIRA1_CAMERA_ID", "FIRA_CAMERA_ID", default=2)


def _available_video_ids() -> list[int]:
    ids: list[int] = []
    for p in glob.glob("/dev/video[0-9]*"):
        base = os.path.basename(p)
        try:
            ids.append(int(base.replace("video", "")))
        except ValueError:
            pass
    return sorted(set(ids))


def _resolve_camera_id(requested_id: int, wait_s: float, fallbacks: list[int]) -> int:
    requested_node = Path(f"/dev/video{int(requested_id)}")
    deadline = time.monotonic() + max(0.0, float(wait_s))
    while time.monotonic() < deadline:
        if requested_node.exists():
            return int(requested_id)
        time.sleep(0.2)

    available = _available_video_ids()
    if int(requested_id) in available:
        return int(requested_id)
    for fid in fallbacks:
        if int(fid) in available:
            print(f"[fira_1] NOTE: /dev/video{requested_id} not found; using /dev/video{fid} instead")
            return int(fid)
    if available:
        chosen = int(available[0])
        print(f"[fira_1] NOTE: /dev/video{requested_id} not found; using /dev/video{chosen} instead")
        return chosen
    raise RuntimeError(
        f"No /dev/video* devices found (requested /dev/video{requested_id}). "
        "Check camera connection and that v4l2 devices are created."
    )

VideoSaveDir = os.environ.get("FIRA_VIDEO_SAVE_DIR", str(_default_home_dir() / "Camera_test" / "video"))
ImageNameFormat = r"{frameId:08}.tiff"

# Disable GUI if no display is available.
HEADLESS = os.environ.get("FIRA_HEADLESS", "").strip() == "1" or not os.environ.get("DISPLAY")

# How long to wait for /dev/video<id> to appear (e.g. after hotplug).
CAMERA_WAIT_S = float(os.environ.get("FIRA_CAMERA_WAIT_S", "5"))

def main():
    t_err = time.time()

    def open_serial_connection(port, baud):
        s = serial.Serial()
        s.port = port
        s.baudrate = baud
        s.open()
        s.flushInput()
        s.flushOutput()
        return s

    def write_read_cmd(con, cmd_write, cmd_read):
        con.write(bytearray.fromhex(cmd_write))
        data = con.read(int(len(cmd_read) / 2))
        if data.hex() == cmd_read:
            return True
        return False

    def init(con):
        """
            cmd_write = 'aa11f0000055'
            cmd_read = '5511f00b00013800120c0e05030c4001e5'
            return write_read_cmd(con, cmd_write, cmd_read)
        """
        ...

    def nuc(con):
        cmd_write = '02182b003303'  # internal shutter
        cmd_read =  '02182b003303'

        return write_read_cmd(con, cmd_write, cmd_read)
        
    def autoFocus(con):
        cmd_write = '021838052503'
        cmd_read =  '021838052503'
        return write_read_cmd(con, cmd_write, cmd_read)
        
    def focusStop(con):
        cmd_write = '021838002003'
        cmd_read =  '021838002003'
        return write_read_cmd(con, cmd_write, cmd_read)
        
    def focusPlus(con):
        cmd_write = '021838012103'
        cmd_read =  '021838012103'
        return write_read_cmd(con, cmd_write, cmd_read)
        
    def focusMinus(con):
        cmd_write = '021838012203'
        cmd_read =  '021838012203'
        return write_read_cmd(con, cmd_write, cmd_read) 
    
    def autoCalicrationOff(con):
        cmd_write = '021830002803'
        cmd_read =  '021830002803'
        return write_read_cmd(con, cmd_write, cmd_read)

    serial_connection = open_serial_connection(CAMERA_PORT, CAMERA_BAUD)
    init(serial_connection)

    if not os.path.exists(VideoSaveDir):
        os.makedirs(VideoSaveDir, exist_ok=True)

    autoCalicrationOff(serial_connection)

    doRecordVideo = False

    cam_id = _resolve_camera_id(CAMERA_ID, wait_s=CAMERA_WAIT_S, fallbacks=[2, 4])

    with Device.from_id(cam_id) as cam:
         for frameId, frame in enumerate(cam):
            try:
                
                raw_image = np.frombuffer(frame.data, dtype=np.uint16).reshape((512, 640))  

                # There is an extra column of zeros
                raw_image = raw_image[:,1:]

                # Swap endianness
                raw_image = raw_image.byteswap()                  

                k = -1 if HEADLESS else cv2.waitKey(1)

                if k & 0xFF == ord("v"):
                    
                    # flip video mode
                    doRecordVideo = not doRecordVideo
                    
                    if doRecordVideo:       
                        # Start new session with timestamped directory or prefix
                        current_time = datetime.now().strftime("%Y%m%d_%H%M%S")
                        video_session_dir = os.path.join(VideoSaveDir, f"fira1_session_{current_time}")
                        os.makedirs(video_session_dir, exist_ok=True)
                        print(f'FIRA 1 is now recording')

                    else:
                        print(f'FIRA 1 STOPPED RECORDING')

                if doRecordVideo:
                    cv2.imwrite(os.path.join(video_session_dir, ImageNameFormat.format(frameId=frameId)),
                        raw_image)

                    if frameId % 20:
                         # Display grayscale image
                        if not HEADLESS:
                            image = cv2.normalize(raw_image, None, 0, 255, cv2.NORM_MINMAX, cv2.CV_8U)
                            cv2.imshow('FIRA1', image)
                else:
                    if not HEADLESS:
                        image = cv2.normalize(raw_image, None, 0, 255, cv2.NORM_MINMAX, cv2.CV_8U)
                        cv2.imshow("FIRA1", image)
                        
                    if k & 0xFF == ord("n"):
                        nuc(serial_connection)

                    if k & 0xFF == ord('r'):
                        shutil.rmtree(VideoSaveDir)
                        os.makedirs(VideoSaveDir)
                                    
                    if k & 0xFF == ord('a'):
                        autoFocus(serial_connection)
                        
                    if k & 0xFF == ord('A'):
                        focusStop(serial_connection)
                        
                    if k & 0xFF == ord('+'):
                        focusPlus(serial_connection)

                    if k & 0xFF == ord('-'):
                        focusMinus

                if k & 0xFF == 27: # ESC to exit (increase delay to ensure window refresh)
                    break
            
            except Exception as e:
                print(e)
                print(time.time()-t_err)
                t_err = time.time()


    if not HEADLESS:
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()