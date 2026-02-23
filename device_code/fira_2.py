import shutil
import serial
import numpy as np
from linuxpy.video.device import Device
import cv2
import threading
import time
import os
from datetime import datetime

CAMERA_PORT = '/dev/ttyUSB1'
CAMERA_BAUD = 115200
CAMERA_ID = 4

VideoSaveDir = '/home/ohad/Camera_test/video'
ImageNameFormat = r'{frameId:08}.tiff'

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
        os.makedirs(VideoSaveDir)

    autoCalicrationOff(serial_connection)

    doRecordVideo = False

    with Device.from_id(CAMERA_ID) as cam:
         for frameId, frame in enumerate(cam):
            try:
                
                raw_image = np.frombuffer(frame.data, dtype=np.uint16).reshape((512, 640))  
               
                # There is an extra column of zeros
                raw_image = raw_image[:,1:]

                # Swap endianness
                raw_image = raw_image.byteswap()                  

                k = cv2.waitKey(1)

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
                    cv2.imwrite(os.path.join(video_session_dir, ImageNameFormat.format(frameId=frameId)),
                        raw_image)

                    if frameId % 20:
                         # Display grayscale image
                        image = cv2.normalize(raw_image, None, 0, 255, cv2.NORM_MINMAX, cv2.CV_8U)
                        cv2.imshow('FIRA2', image)
                else:
                    image = cv2.normalize(raw_image, None, 0, 255, cv2.NORM_MINMAX, cv2.CV_8U)
                    cv2.imshow("FIRA2", image)
                    
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


    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()