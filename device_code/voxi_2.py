import shutil
import serial
import numpy as np
from linuxpy.video.device import Device
import cv2
import time
import os
import serial.tools.list_ports
import subprocess
from datetime import datetime

def get_video_devices():
    # Run the command
    result = subprocess.run(['v4l2-ctl', '--list-devices'], stdout=subprocess.PIPE, text=True)
    output = result.stdout

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

    # Filter and get the first video device for specified names
    targets = ['SENSIA-CAM', '1080P USB FHD Camera']
    result_dict = {}

    for name in targets:
        for device_name, paths in devices.items():
            if device_name.startswith(name):
                first_video = next((p for p in paths if '/dev/video' in p), None)
                if first_video:
                    result_dict[name] = first_video[-1]
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


CAMERA_PORT = find_camera_port(PRODUCT_NAME)
CAMERA_BAUD = 115200
CAMERA_ID = get_video_devices()[PRODUCT_NAME]
print(CAMERA_ID)

VideoSaveDir = '/home/ohad/Camera_test/video'
ImageNameFormat = r'{frameId:08}.tiff'

def main():
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
        nuc(serial_connection)
        
        """
        cmd_write = 'aa11f0000055'
        cmd_read = '5511f00b00013800120c0e05030c4001e5'
        return write_read_cmd(con, cmd_write, cmd_read)
        """
        pass

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

    serial_connection = open_serial_connection(CAMERA_PORT, CAMERA_BAUD)
    init(serial_connection)

    if not os.path.exists(VideoSaveDir):
        os.makedirs(VideoSaveDir)
    
    doRecordVideo = False
       
    with Device.from_id(CAMERA_ID) as cam:
         for frameId, frame in enumerate(cam):
            try:
                raw_image = np.frombuffer(frame.data, dtype=np.uint16).reshape((480, 640))    
                    
                k = cv2.waitKey(1)

                if k & 0xFF == ord("v"):
                    # flip video mode
                    doRecordVideo = not doRecordVideo

                    if doRecordVideo:       
                        # Start new session with timestamped directory or prefix
                        current_time = datetime.now().strftime("%Y%m%d_%H%M%S")
                        video_session_dir = os.path.join(VideoSaveDir, f"voxi2_session_{current_time}")
                        os.makedirs(video_session_dir, exist_ok=True)
                        print(f'VOXI 2 is now recording')

                    else:
                        print(f'VOXI 2 STOPPED RECORDING')
  
                if doRecordVideo: 
                    cv2.imwrite(os.path.join(video_session_dir, ImageNameFormat.format(frameId=frameId)),
                                    raw_image)
                    if frameId % 20:
                        image = cv2.normalize(raw_image, None, 0, 255, cv2.NORM_MINMAX, cv2.CV_8U)
                        cv2.imshow("VOXI 2", image)                    

                else:
                    image = cv2.normalize(raw_image, None, 0, 255, cv2.NORM_MINMAX, cv2.CV_8U)
                    cv2.imshow("VOXI 2", image)    

                    if k & 0xFF == ord("n"):
                        nuc(serial_connection)
        
                    #if k & 0xFF == ord('s'):
                    #    threading.Thread(target=scs, args=(serial_connection,)).start()

                    if k & 0xFF == ord('r'):
                        shutil.rmtree(VideoSaveDir)
                        os.makedirs(VideoSaveDir)


                if k & 0xFF == 27:  # ESC to exit (increase delay to ensure window refresh)
                    break
            
            except Exception as e:
                print(e)


    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
