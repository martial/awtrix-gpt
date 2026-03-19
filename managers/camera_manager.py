import cv2
import logging
import os
from datetime import datetime
from typing import Optional, Tuple
import threading
import time

from config_loader import load_config


class CameraManager:
    def __init__(self):
        """Initialize camera manager"""
        self.logger = logging.getLogger(__name__)
        self.config = load_config()

        self.camera: Optional[cv2.VideoCapture] = None
        self.lock = threading.Lock()
        self.is_initialized = False

        # Create photos directory
        self.photos_dir = os.path.join(os.path.dirname(__file__),
                                       self.config['camera']['settings']['photo_directory'])
        os.makedirs(self.photos_dir, exist_ok=True)

        # Initialize camera
        self.initialize_camera()

    @staticmethod
    def list_available_cameras():
        """List available cameras with metadata for the config UI."""
        available_cameras = []
        for i in range(10):
            try:
                cap = cv2.VideoCapture(i)
                if cap.isOpened():
                    backend = cap.getBackendName()
                    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                    fps = cap.get(cv2.CAP_PROP_FPS)
                    available_cameras.append({
                        'index': i,
                        'name': f'Camera {i}',
                        'backend': backend,
                        'resolution': f'{w}x{h}',
                        'fps': round(fps, 1) if fps > 0 else 'N/A'
                    })
                cap.release()
            except Exception:
                pass
        return available_cameras

    def initialize_camera(self):
        """Initialize the camera with specified settings"""
        with self.lock:
            if self.is_initialized:
                self.logger.info("Camera is already initialized.")
                return

            try:
                if self.camera is not None:
                    self.camera.release()

                self.camera = cv2.VideoCapture(self.config['camera']['index'])
                time.sleep(2)

                if not self.camera.isOpened():
                    self.logger.warning(f"Failed to open camera at index {self.config['camera']['index']}")
                    self.camera = None
                    return

                width = self.config['camera']['resolution'].get('width', 640)
                height = self.config['camera']['resolution'].get('height', 480)
                self.camera.set(cv2.CAP_PROP_FRAME_WIDTH, width)
                self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, height)

                self.logger.info(f"Camera initialized: index {self.config['camera']['index']}")
                ret, _ = self.camera.read()
                if not ret:
                    raise Exception("Camera initialized but failed to capture test frame")

                self.is_initialized = True

            except Exception as e:
                self.logger.error(f"Error initializing camera: {str(e)}")
                if self.camera is not None:
                    self.camera.release()
                    self.camera = None
                self.is_initialized = False
                raise

    def take_picture(self, filename: Optional[str] = None) -> Optional[str]:
        """Take a picture and save it to file"""
        with self.lock:
            try:
                if not self.is_initialized:
                    self.initialize_camera()

                ret, frame = self.camera.read()
                if not ret or frame is None:
                    raise Exception("Failed to capture frame.")

                if filename is None:
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    filename = f"photo_{timestamp}.jpg"

                filepath = os.path.join(self.photos_dir, filename)
                cv2.imwrite(filepath, frame)
                self.logger.info(f"Picture saved to {filepath}")
                return filepath

            except Exception as e:
                self.logger.error(f"Error taking picture: {str(e)}")
                return None

    def get_preview_frame(self) -> tuple[Optional[bytes], Optional[bytes]]:
        """Get a single frame as JPEG bytes for preview, returns (original, thresholded)"""
        with self.lock:
            try:
                if not self.is_initialized:
                    self.initialize_camera()

                for _ in range(5):
                    self.camera.read()

                ret, frame = self.camera.read()
                if not ret or frame is None:
                    raise Exception("Failed to capture preview frame.")

                original = frame.copy()
                frame = cv2.rotate(frame, cv2.ROTATE_180)

                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                blurred = cv2.GaussianBlur(gray, (5, 5), 0)
                threshold = cv2.adaptiveThreshold(
                    blurred, 255,
                    cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                    cv2.THRESH_BINARY,
                    51, 2
                )

                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                debug_dir = os.path.join(self.photos_dir, 'debug')
                os.makedirs(debug_dir, exist_ok=True)

                original_path = os.path.join(debug_dir, f'original_{timestamp}.jpg')
                cv2.imwrite(original_path, original)
                threshold_path = os.path.join(debug_dir, f'threshold_{timestamp}.jpg')
                cv2.imwrite(threshold_path, threshold)
                self.logger.info(f"Saved debug images: \nOriginal: {original_path}\nThreshold: {threshold_path}")

                _, original_buffer = cv2.imencode('.jpg', original)
                _, threshold_buffer = cv2.imencode('.jpg', threshold)

                return original_buffer.tobytes(), threshold_buffer.tobytes()

            except Exception as e:
                self.logger.error(f"Error getting preview frame: {str(e)}")
                return None, None

    def close(self):
        """Properly close the camera"""
        with self.lock:
            if self.camera is not None:
                self.camera.release()
                self.camera = None
                self.is_initialized = False
                self.logger.info("Camera released")

    def __del__(self):
        """Destructor to ensure camera is properly released"""
        self.close()
