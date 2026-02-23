import atexit
import faulthandler
import logging
import os
import shutil
import signal
import sys
import threading
import time
import traceback

_LOG_FILE = (os.environ.get("VOXI_LOG_FILE") or "/tmp/voxi_1.log").strip() or "/tmp/voxi_1.log"
_logger = logging.getLogger("voxi_1")
if not _logger.handlers:
    _logger.setLevel(logging.INFO)
    try:
        _fh = logging.FileHandler(_LOG_FILE)
        _fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        _logger.addHandler(_fh)
    except Exception:
        # If file logging can't be set up (permissions/fs), still run.
        pass


def _log(msg: str) -> None:
    try:
        _logger.info(msg)
    except Exception:
        pass
    try:
        print(msg, flush=True)
    except Exception:
        pass


def _dump_all_threads(reason: str) -> None:
    try:
        _log(f"[voxi_1] DUMP: {reason}")
        with open(_LOG_FILE, "a", encoding="utf-8", errors="ignore") as f:
            f.write("\n=== THREAD DUMP: " + reason + " ===\n")
            faulthandler.dump_traceback(file=f, all_threads=True)
            f.write("\n")
    except Exception:
        pass


_stage_lock = threading.Lock()
_stage = "import"


def _set_stage(stage: str) -> None:
    global _stage
    with _stage_lock:
        _stage = stage
    _log(f"[voxi_1] stage={stage}")


def _watchdog_thread(timeout_s: float) -> None:
    time.sleep(max(0.0, float(timeout_s)))
    with _stage_lock:
        stage = _stage
    if stage not in {"streaming", "exited"}:
        _dump_all_threads(f"watchdog timeout after {timeout_s}s (stage={stage})")


def _install_signal_dump() -> None:
    # Allow: `kill -USR1 <pid>` to dump stacks into the log.
    try:
        signal.signal(signal.SIGUSR1, lambda *_: _dump_all_threads("SIGUSR1"))
    except Exception:
        pass


def _install_atexit() -> None:
    def _on_exit() -> None:
        _set_stage("exited")

    atexit.register(_on_exit)


_install_signal_dump()
_install_atexit()

# Record that the module imported successfully (helps when it never reaches main()).
try:
    _set_stage("imported")
except Exception:
    pass


def _maybe_reexec_in_venv() -> None:
    """If running under system python without deps, prefer a known venv.

    This is intentionally simple: if ~/fira-venv exists, re-exec into it once.
    """

    # Prevent loops.
    if os.environ.get("VOXI_REEXEC", "") == "1":
        return

    # If already in a venv, don't re-exec.
    try:
        if sys.prefix != sys.base_prefix:
            return
    except Exception:
        return

    venv_python = os.path.expanduser("~/fira-venv/bin/python")
    if not os.path.exists(venv_python):
        return

    try:
        os.environ["VOXI_REEXEC"] = "1"
        _log(f"[voxi_1] Re-execing into venv interpreter: {venv_python}")
        os.execv(venv_python, [venv_python, *sys.argv])
    except Exception as e:
        _log(f"[voxi_1] WARN: venv re-exec failed: {e}")


_maybe_reexec_in_venv()

try:
    # If the process gets stuck, this helps capture where.
    faulthandler.enable(open(_LOG_FILE, "a"))
except Exception:
    pass


import serial
import numpy as np
try:
    from linuxpy.video.device import Device
except ModuleNotFoundError as e:
    raise SystemExit(
        "Missing Python module 'linuxpy'. Install it (e.g. in a venv: 'python3 -m venv v && v/bin/pip install linuxpy') "
        "and run this script with that venv's python."
    ) from e
try:
    import cv2
except ModuleNotFoundError as e:
    raise SystemExit(
        "Missing Python module 'cv2' (OpenCV). Install it (e.g. 'sudo apt-get install python3-opencv') "
        "or run this script inside a virtualenv that has opencv-python installed."
    ) from e
import serial.tools.list_ports
import subprocess
import shutil as _shutil
from pathlib import Path
from datetime import datetime
from typing import Any

def get_video_devices(timeout_s: float = 2.0) -> dict[str, list[int]]:
    if _shutil.which("v4l2-ctl") is None:
        return {}

    try:
        result = subprocess.run(
            ["v4l2-ctl", "--list-devices"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=float(timeout_s),
            check=False,
        )
        output = result.stdout or ""
    except subprocess.TimeoutExpired:
        # Avoid hanging at startup if v4l2-ctl gets stuck.
        return {}

    # Parse the output
    lines = output.strip().split('\n')
    devices = {}
    current_device = None
    device_paths = []

    for line in lines:
        if not line.startswith('\t'):  # New device
            if current_device:
                devices[current_device] = device_paths
            current_device = line.strip()
            device_paths = []
        else:
            device_paths.append(line.strip())
    
    if current_device:
        devices[current_device] = device_paths

    # Filter and get the video device ids for specified names
    targets = ['SENSIA-CAM', '1080P USB FHD Camera']
    result_dict: dict[str, list[int]] = {}

    for name in targets:
        for device_name, paths in devices.items():
            if device_name.startswith(name):
                vids: list[int] = []
                for p in paths:
                    if "/dev/video" not in p:
                        continue
                    try:
                        vids.append(int(os.path.basename(p).replace("video", "")))
                    except Exception:
                        continue
                if vids:
                    result_dict[name] = sorted(set(vids))
                break

    return result_dict


# def find_camera_port(target_vid, target_pid):
#     ports = serial.tools.list_ports.comports()
#     for port in ports:
#         if port.vid is not None and port.pid is not None:
#             if f"{port.vid:04x}" == target_vid.lower() and f"{port.pid:04x}" == target_pid.lower():
#                 return port.device
#     return None  

def find_camera_port(cam_product):
    ports = serial.tools.list_ports.comports()
    for port in ports:
        if cam_product == port.product:
            return port.device
    return None  

# Replace with your device's VID and PID
# TARGET_VID = "21331"
# TARGET_PID = "25859" #for ACM0

# TARGET_PID = "25858" #for ACM1
PRODUCT_NAME = 'SENSIA-CAM'


def _default_home_dir() -> Path:
    sudo_user = (os.environ.get("SUDO_USER") or "").strip()
    if os.geteuid() == 0 and sudo_user:
        candidate = Path("/home") / sudo_user
        if candidate.is_dir():
            return candidate
    return Path.home()


def _env_flag(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def _is_headless() -> bool:
    raw = _env_flag("VOXI_HEADLESS")
    if raw == "1":
        return True
    if raw == "0":
        return False
    return not bool(os.environ.get("DISPLAY"))


def _available_video_ids() -> list[int]:
    ids: list[int] = []
    for p in Path("/dev").glob("video*"):
        name = p.name
        if not name.startswith("video"):
            continue
        try:
            ids.append(int(name.replace("video", "")))
        except ValueError:
            pass
    return sorted(set(ids))


def _video_ids_from_sysfs_name(*needles: str) -> list[int]:
    needles_l = [n.lower() for n in needles if (n or "").strip()]
    if not needles_l:
        return []

    ids: list[int] = []
    base = Path("/sys/class/video4linux")
    if not base.exists():
        return []

    for vdir in base.glob("video*"):
        try:
            vid = int(vdir.name.replace("video", ""))
        except ValueError:
            continue
        name_path = vdir / "name"
        try:
            vname = name_path.read_text(encoding="utf-8", errors="ignore").strip().lower()
        except Exception:
            continue
        if any(n in vname for n in needles_l):
            ids.append(vid)
    return sorted(set(ids))


def _pick_camera_ids(product_name: str) -> list[int]:
    env_id = _env_flag("VOXI_CAMERA_ID")
    if env_id:
        return [int(env_id)]

    # Most reliable: sysfs name matching (no external commands).
    sysfs_ids = _video_ids_from_sysfs_name(product_name, "SENSIA")
    if sysfs_ids:
        # Keep ascending order; some devices expose a non-capture node at the higher index.
        return sorted(sysfs_ids)

    # Next: v4l2-ctl mapping by product name.
    timeout_s = float(_env_flag("VOXI_V4L2_CTL_TIMEOUT_S") or "5")
    mapping = get_video_devices(timeout_s=timeout_s)
    ids = mapping.get(product_name) or []
    if ids:
        return sorted(ids)

    # Last resort: try all /dev/video* in ascending order.
    return _available_video_ids()


def _frame_to_u16_image(frame: Any, *, width: int, height: int) -> np.ndarray:
    raw = np.frombuffer(frame.data, dtype=np.uint16)
    needed = int(width) * int(height)
    if needed <= 0:
        raise ValueError(f"Invalid frame shape: width={width} height={height}")
    if raw.size < needed:
        raise ValueError(
            f"Frame too small: {raw.size} uint16 values (need {needed} for {height}x{width}). "
            "This often indicates the wrong /dev/video* node was selected."
        )
    if raw.size != needed:
        # Some drivers append metadata/padding; trim to expected size.
        raw = raw[:needed]
    return raw.reshape((int(height), int(width)))


ImageNameFormat = r"{frameId:08}.tiff"

def main():
    _set_stage("main")
    watchdog_s = float(_env_flag("VOXI_WATCHDOG_S") or "10")
    threading.Thread(target=_watchdog_thread, args=(watchdog_s,), daemon=True).start()

    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass

    headless = _is_headless()
    camera_port = _env_flag("VOXI_CAMERA_PORT") or find_camera_port(PRODUCT_NAME)
    camera_baud = int(_env_flag("VOXI_CAMERA_BAUD") or "115200")
    camera_ids = _pick_camera_ids(PRODUCT_NAME)

    video_save_dir = _env_flag("VOXI_VIDEO_SAVE_DIR") or str(_default_home_dir() / "Camera_test" / "video")

    _log(
        f"[voxi_1] pid={os.getpid()} headless={headless} DISPLAY={os.environ.get('DISPLAY')!r} "
        f"serial_port={camera_port!r} baud={camera_baud} camera_ids={camera_ids} save_dir={video_save_dir!r} "
        f"log_file={_LOG_FILE!r}"
    )

    if headless:
        print(
            "[voxi_1] NOTE: headless mode is enabled (no DISPLAY detected). "
            "If you expect a GUI window, run from the desktop session (not over plain SSH), "
            "avoid sudo (or use 'sudo -E'), or export DISPLAY. You can also set VOXI_HEADLESS=0.",
            flush=True,
        )

    serial_timeout_s = float(_env_flag("VOXI_SERIAL_TIMEOUT_S") or "1")

    def open_serial_connection(port, baud):
        if not port:
            raise RuntimeError(
                "No serial port detected for camera. Set VOXI_CAMERA_PORT (e.g. /dev/ttyUSB0) or check USB serial device."
            )
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
            # Older pyserial uses flushInput/flushOutput
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
        except Exception as e:
            print(f"[voxi_1] WARN: serial IO error: {e}", flush=True)
            return False

        if not data or len(data) != expected:
            return False
        return data.hex() == cmd_read

    def init(con):
        # Avoid hanging forever if the camera doesn't respond on serial.
        for attempt in range(1, 4):
            if nuc(con):
                return
            print(f"[voxi_1] WARN: nuc() no response (attempt {attempt}/3)", flush=True)
            time.sleep(0.2)
        
        """
        cmd_write = 'aa11f0000055'
        cmd_read = '5511f00b00013800120c0e05030c4001e5'
        return write_read_cmd(con, cmd_write, cmd_read)
        """
        return

    def nuc(con):
        cmd_write = 'aa1685040010000000a7'
        cmd_read = '551685000010'
        return write_read_cmd(con, cmd_write, cmd_read)
    
    def shutter_close_simple(con):
        cmd_write = 'aa18f401000148'
        cmd_read = '5518f400009f'
        return write_read_cmd(con, cmd_write, cmd_read)
        
    def shutter_close(con):
        cmd_write_list = ['aa18f401000049', 'aa19f4000049']
        cmd_read_list = ['5518f400009f', '5519f410000101000101171700160000000000000046']
        for (cmd_write, cmd_read) in zip(cmd_write_list, cmd_read_list):
            status = write_read_cmd(con, cmd_write, cmd_read)
            if not status: return False
        return True
        
    def shutter_open(con):
        cmd_write_list = ['aa18f401000148', 'aa19f4000049']
        cmd_read_list = ['5518f400009f', '5519f410000102000001171701160000000000000045']
        for (cmd_write, cmd_read) in zip(cmd_write_list, cmd_read_list):
            status = write_read_cmd(con, cmd_write, cmd_read)
            if not status: return False
        return True
        
    def compensation_start(con):
        cmd_write = 'aa08f000005e'
        cmd_read = '5508f00000b3'
        return write_read_cmd(con, cmd_write, cmd_read)

    def scs(con):
        while not shutter_close(con):
            print("shutter close error")
        time.sleep(1)
        while not compensation_start(con):
            print("compensation start error")
        time.sleep(1)
        while not shutter_open(con):
            print("shutter open error")
        print("scs success")         

    _set_stage("serial_open")
    serial_connection = open_serial_connection(camera_port, camera_baud)
    _set_stage("serial_init")
    init(serial_connection)

    if not os.path.exists(video_save_dir):
        os.makedirs(video_save_dir, exist_ok=True)
    
    doRecordVideo = False

    frame_width = int(_env_flag("VOXI_FRAME_WIDTH") or "640")
    frame_height = int(_env_flag("VOXI_FRAME_HEIGHT") or "480")

    if not headless:
        _set_stage("gui_init")
        try:
            cv2.namedWindow("VOXI 1", cv2.WINDOW_NORMAL)
            # Make the initial window size sensible; OpenCV sometimes starts very small.
            win_w = int(_env_flag("VOXI_WINDOW_WIDTH") or str(frame_width))
            win_h = int(_env_flag("VOXI_WINDOW_HEIGHT") or str(frame_height))
            if win_w > 0 and win_h > 0:
                cv2.resizeWindow("VOXI 1", win_w, win_h)
        except Exception as e:
            # If X/Wayland is not accessible (common with sudo/SSH), avoid a silent failure.
            _log(f"[voxi_1] WARN: GUI init failed, falling back to headless: {e}")
            headless = True
    max_bad_frames = int(_env_flag("VOXI_MAX_BAD_FRAMES") or "3")

    # Try candidate camera nodes until one streams frames that match the expected shape.
    last_open_err: Exception | None = None
    _set_stage("video_open")
    for cid in (camera_ids or [0]):
        try:
            bad_frames = 0
            with Device.from_id(int(cid)) as cam:
                print(f"[voxi_1] Using /dev/video{int(cid)}", flush=True)
                _set_stage("streaming")
                for frameId, frame in enumerate(cam):
                    try:
                        raw_image = _frame_to_u16_image(frame, width=frame_width, height=frame_height)
                        bad_frames = 0
                    except Exception as e:
                        bad_frames += 1
                        if bad_frames == 1 or bad_frames % 30 == 0:
                            print(f"[voxi_1] WARN: {e}", flush=True)
                        if bad_frames >= max_bad_frames:
                            raise RuntimeError(
                                f"Too many bad frames on /dev/video{int(cid)} (max_bad_frames={max_bad_frames})"
                            ) from e
                        continue

                    if doRecordVideo:
                        cv2.imwrite(
                            os.path.join(video_session_dir, ImageNameFormat.format(frameId=frameId)),
                            raw_image,
                        )
                        if frameId % 20 and not headless:
                            image = cv2.normalize(raw_image, None, 0, 255, cv2.NORM_MINMAX, cv2.CV_8U)
                            cv2.imshow("VOXI 1", image)
                    else:
                        if not headless:
                            image = cv2.normalize(raw_image, None, 0, 255, cv2.NORM_MINMAX, cv2.CV_8U)
                            cv2.imshow("VOXI 1", image)

                    # Call waitKey AFTER imshow so the window reliably appears/refreshes.
                    k = -1 if headless else cv2.waitKey(1)

                    if k & 0xFF == ord("v"):
                        doRecordVideo = not doRecordVideo
                        if doRecordVideo:
                            current_time = datetime.now().strftime("%Y%m%d_%H%M%S")
                            video_session_dir = os.path.join(video_save_dir, f"voxi1_session_{current_time}")
                            os.makedirs(video_session_dir, exist_ok=True)
                            print("VOXI 1 is now recording", flush=True)
                        else:
                            print("VOXI 1 STOPPED RECORDING", flush=True)

                    if not doRecordVideo:
                        if k & 0xFF == ord("n"):
                            nuc(serial_connection)
                        if k & 0xFF == ord("r"):
                            shutil.rmtree(video_save_dir)
                            os.makedirs(video_save_dir, exist_ok=True)

                    if k & 0xFF == 27:
                        return

                # If the iterator ends, stop trying other ids.
                return

        except Exception as e:
            last_open_err = e
            print(f"[voxi_1] NOTE: /dev/video{int(cid)} failed: {e}", flush=True)
            continue

    raise SystemExit(f"Could not open a working camera device. Last error: {last_open_err}")


    if not headless:
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
