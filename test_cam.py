import cv2
import time

cap = cv2.VideoCapture(0)  # or use "/dev/video0"
time.sleep(2)  # Wait for the camera to initialize

if not cap.isOpened():
    raise Exception("Failed to open camera at index 0")

cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

# Test capturing a frame
ret, frame = cap.read()
if ret:
    cv2.imshow("Test Frame", frame)
    cv2.waitKey(0)  # Press any key to close the window
else:
    print("Failed to capture an image.")
cap.release()
cv2.destroyAllWindows()
