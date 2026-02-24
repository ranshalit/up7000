import shutil
import serial
import numpy as np
from linuxpy.video.device import Device
try:
    import cv2
except ModuleNotFoundError as e:
    raise SystemExit(
        "Missing Python module 'cv2' (OpenCV). Install it (e.g. 'sudo apt-get install python3-opencv') "
        "or run this script inside a virtualenv that has opencv-python installed."
    ) from e
import threading
import time
import os
import glob
import sys
from pathlib import Path
from datetime import datetime


def _find_serial_port(product_name: str) -> str:
    try:
        import serial.tools.list_ports
    except Exception:
        return ""

    for port in serial.tools.list_ports.comports():
        if (port.product or "") == product_name:
            return port.device or ""
    return ""

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


def _available_video_ids() -> list[int]:
    ids: list[int] = []
    for p in glob.glob("/dev/video[0-9]*"):
        base = os.path.basename(p)
        try:
            ids.append(int(base.replace("video", "")))
        except ValueError:
            pass
    return sorted(set(ids))


def _env_flag(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def _is_headless() -> bool:
    raw = _env_flag("FIRA_HEADLESS")
    if raw == "1":
        return True
    if raw == "0":
        return False
    return not bool(os.environ.get("DISPLAY"))


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

    # Strict mode: caller can pass an empty fallback list to disable probing.
    if not fallbacks:
        raise RuntimeError(
            f"Requested /dev/video{requested_id} not found. "
            "Strict camera-id mode is enabled; refusing to fall back to other /dev/video* nodes."
        )
    for fid in fallbacks:
        if int(fid) in available:
            print(f"[fira_2] NOTE: /dev/video{requested_id} not found; using /dev/video{fid} instead")
            return int(fid)
    if available:
        chosen = int(available[0])
        print(f"[fira_2] NOTE: /dev/video{requested_id} not found; using /dev/video{chosen} instead")
        return chosen
    raise RuntimeError(
        f"No /dev/video* devices found (requested /dev/video{requested_id}). "
        "Check camera connection and that v4l2 devices are created."
    )


CAMERA_PORT = (
    os.environ.get("FIRA2_CAMERA_PORT")
    or os.environ.get("FIRA_CAMERA_PORT")
    or _find_serial_port("SENSIA-CAM")
    or "/dev/ttyACM0"
)
CAMERA_BAUD = _get_env_int("FIRA2_CAMERA_BAUD", "FIRA_CAMERA_BAUD", default=115200)
CAMERA_ID = _get_env_int("FIRA2_CAMERA_ID", "FIRA_CAMERA_ID", default=3)

VideoSaveDir = os.environ.get("FIRA_VIDEO_SAVE_DIR", str(_default_home_dir() / "Camera_test" / "video"))
ImageNameFormat = r"{frameId:08}.tiff"

HEADLESS = _is_headless()
CAMERA_WAIT_S = float(os.environ.get("FIRA_CAMERA_WAIT_S", "5"))

def main():
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass

    headless = _is_headless()
    print(
        f"[fira_2] headless={headless} DISPLAY={os.environ.get('DISPLAY')!r} "
        f"serial_port={CAMERA_PORT!r} baud={CAMERA_BAUD} camera_id={CAMERA_ID}",
        flush=True,
    )
    if headless:
        print(
            "[fira_2] NOTE: headless mode is enabled (no DISPLAY detected). "
            "If you expect a GUI window, run from the desktop session (not plain SSH), "
            "avoid sudo (or use 'sudo -E'), or set FIRA_HEADLESS=0.",
            flush=True,
        )

    serial_timeout_s = float(_env_flag("FIRA_SERIAL_TIMEOUT_S") or "1")
    t_err = time.time()

    def open_serial_connection(port, baud):
        s = serial.Serial(
            port=port,
            baudrate=baud,
            timeout=serial_timeout_s,
            write_timeout=serial_timeout_s,
        )
        try:
            s.reset_input_buffer()
            s.reset_output_buffer()
        except Exception:
            try:
                s.flushInput()
                s.flushOutput()
            except Exception:
                pass
        return s

    def write_read_cmd(con, cmd_write, cmd_read):
        try:
            con.write(bytearray.fromhex(cmd_write))
            expected = int(len(cmd_read) / 2)
            data = con.read(expected)
        except Exception:
            return False
        if not data or len(data) != expected:
            return False
        return data.hex() == cmd_read

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

    if not autoCalicrationOff(serial_connection):
        print("[fira_2] WARN: autoCalicrationOff: no response", flush=True)

    doRecordVideo = False

    # Strict by default: do not silently switch to another /dev/video*.
    strict_camera_id = _env_flag("FIRA_STRICT_CAMERA_ID") != "0"
    if strict_camera_id:
        cam_id = _resolve_camera_id(CAMERA_ID, wait_s=CAMERA_WAIT_S, fallbacks=[])
    else:
        cam_id = _resolve_camera_id(CAMERA_ID, wait_s=CAMERA_WAIT_S, fallbacks=[3, 2])

    if not headless:
        cv2.namedWindow("FIRA2", cv2.WINDOW_NORMAL)
        try:
            cv2.resizeWindow("FIRA2", 640, 480)
        except Exception:
            pass

    with Device.from_id(cam_id) as cam:
         for frameId, frame in enumerate(cam):
            try:
                
                raw = np.frombuffer(frame.data, dtype=np.uint16)
                width = int(os.environ.get("FIRA_FRAME_WIDTH", "640"))
                if width <= 0 or raw.size % width != 0:
                    raise ValueError(f"Unexpected frame size: {raw.size} uint16 values (width={width})")
                height = raw.size // width
                raw_image = raw.reshape((height, width))
               
                # There is an extra column of zeros
                raw_image = raw_image[:,1:]

                # Swap endianness
                raw_image = raw_image.byteswap()                  

                if not headless:
                    image = cv2.normalize(raw_image, None, 0, 255, cv2.NORM_MINMAX, cv2.CV_8U)
                    cv2.imshow("FIRA2", image)

                k = -1 if headless else cv2.waitKey(1)

                if k & 0xFF == ord("v"):
                    
                    # flip video mode
                    doRecordVideo = not doRecordVideo
                    
                    if doRecordVideo:       
                        # Start new session with timestamped directory or prefix
                        current_time = datetime.now().strftime("%Y%m%d_%H%M%S")
                        video_session_dir = os.path.join(VideoSaveDir, f"fira2_session_{current_time}")
                        os.makedirs(video_session_dir, exist_ok=True)
                        print(f'FIRA 2 is now recording')

                    else:
                        print(f'FIRA 2 STOPPED RECORDING')

                if doRecordVideo:
                    cv2.imwrite(
                        os.path.join(video_session_dir, ImageNameFormat.format(frameId=frameId)),
                        raw_image,
                    )
                    
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


    if not headless:
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()