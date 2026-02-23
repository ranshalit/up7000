import cv2
import numpy as np
from PIL import Image
import os
import glob

# Directory path
# base_path = '/home/ohad/I_W/Camera_Test/voxi/Video/session_20250929_123914' #voxi
# base_path = "/home/ohad/firaOut/Video/fira1session_20250929_123912"
base_path = '/home/ohad/Camera_test/video/fira2_session_20251104_143020'
# Remove trailing slash
base_path = base_path.rstrip("/")


# Find all TIFF files matching voxi*.tiff
if 'fira' in base_path:
    tiff_files = sorted(glob.glob(os.path.join(base_path, "*.tiff")))
elif 'voxi' in base_path:
    tiff_files = sorted(glob.glob(os.path.join(base_path, "*.tiff")))
else:
    print('Files are not in order')
    
# Check if any TIFF files were found
if not tiff_files:
    print(f"No TIFF files found in {base_path} matching pattern 'voxi*.tiff'")
    print("Available files in directory:")
    for file in os.listdir(base_path):
        if file.endswith(('.tiff', '.tif')):
            print(f" - {file}")
    exit()

print(f"Found {len(tiff_files)} TIFF files for video playback")

# Function to convert 16-bit PIL image to 8-bit OpenCV format
def pil_to_opencv_16bit(pil_image):
    try:
        # Convert PIL image to numpy array (16-bit)
        img_array = np.array(pil_image, dtype=np.uint16)
        
        # Handle grayscale or RGB
        if len(img_array.shape) == 2:  # Grayscale
            # Normalize 16-bit (0-65535) to 8-bit (0-255)
            img_array = cv2.normalize(img_array, None, 0, 255, cv2.NORM_MINMAX)
            img_array = img_array.astype(np.uint8)
            # Convert to BGR for OpenCV display
            img_array = cv2.cvtColor(img_array, cv2.COLOR_GRAY2BGR)
        elif len(img_array.shape) == 3:  # RGB
            # Normalize each channel to 8-bit
            img_array = cv2.normalize(img_array, None, 0, 255, cv2.NORM_MINMAX)
            img_array = img_array.astype(np.uint8)
            # Convert RGB to BGR
            img_array = cv2.cvtColor(img_array, cv2.COLOR_RGB2BGR)
        else:
            raise ValueError("Unsupported image format")
        return img_array
    except Exception as e:
        print(f"Error converting image: {e}")
        return None

# Set frame rate for playback
fps = 30
delay = int(1000 / fps)  # Delay in milliseconds

# Initialize window
cv2.namedWindow("TIFF Video", cv2.WINDOW_NORMAL)

# Display each TIFF as a video frame
for frame_number, tiff_file in enumerate(tiff_files):
    try:
        formatted_number = f"{frame_number + 121:06d}"  # Start from 000060
        print(f"Processing frame {formatted_number}: {os.path.basename(tiff_file)}")
        tiff = Image.open(tiff_file)
        if tiff.mode not in ('I;16', 'RGB'):
            print(f"Warning: {tiff_file} is not 16-bit grayscale or RGB (mode: {tiff.mode})")
        frame = pil_to_opencv_16bit(tiff)
        tiff.close()
        if frame is None:
            print(f"Skipping frame {formatted_number}: Failed to convert")
            continue
        # Add frame number
        cv2.putText(frame, f"Frame: {formatted_number}", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
        cv2.imshow("TIFF Video", frame)
        # Force display update
        key = cv2.waitKey(delay) & 0xFF
        
        if key & 0xFF == 27: # ESC to exit (increase delay to ensure window refresh)
            break

    except Exception as e:
        print(f"Error processing {tiff_file}: {e}")
        tiff.close()
        continue

# Clean up
cv2.destroyAllWindows()
print("Playback completed")