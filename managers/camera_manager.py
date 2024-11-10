import cv2
import logging
import os
from datetime import datetime
from typing import Optional, Tuple
import threading
import time
import yaml

class CameraManager:
    def __init__(self):
        """Initialize camera manager"""
        self.logger = logging.getLogger(__name__)
        
        # Load configuration
        try:
            with open('config.yaml', 'r') as file:
                self.config = yaml.safe_load(file)
        except Exception as e:
            self.logger.error(f"Error loading config: {str(e)}")
            raise

        self.camera: Optional[cv2.VideoCapture] = None
        self.lock = threading.Lock()
        
        # Create photos directory
        self.photos_dir = os.path.join(os.path.dirname(__file__), 
                                     self.config['camera']['settings']['photo_directory'])
        os.makedirs(self.photos_dir, exist_ok=True)
        
        # Initialize camera
        self.initialize_camera()

    def list_available_cameras(self):
        """List all available cameras"""
        available_cameras = []
        max_cameras_to_check = 10  # Adjust this number if needed
        
        for index in range(max_cameras_to_check):
            cap = cv2.VideoCapture(index)
            if cap.isOpened():
                try:
                    backend = cap.getBackendName()
                    name = f"Camera {index}"
                    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                    fps = int(cap.get(cv2.CAP_PROP_FPS))
                    available_cameras.append({
                        'index': index,
                        'name': name,
                        'backend': backend,
                        'resolution': f"{width}x{height}",
                        'fps': fps
                    })
                except:
                    available_cameras.append({
                        'index': index,
                        'name': f"Camera {index}",
                        'backend': 'Unknown',
                        'resolution': 'Unknown',
                        'fps': 'Unknown'
                    })
                cap.release()
                
        return available_cameras
    
    def initialize_camera(self):
        """Initialize the camera with specified settings"""
        with self.lock:
            try:
                if self.camera is not None:
                    self.camera.release()
                
                self.camera = cv2.VideoCapture(self.config['camera']['index'])
                time.sleep(2)  # Wait for camera to initialize
                
                if not self.camera.isOpened():
                    raise Exception(f"Failed to open camera at index {self.config['camera']['index']}")

                # Set default resolution if specified
                width = self.config['camera']['resolution'].get('width', 640)
                height = self.config['camera']['resolution'].get('height', 480)
                self.camera.set(cv2.CAP_PROP_FRAME_WIDTH, width)
                self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, height)

                self.logger.info(f"Camera initialized: index {self.config['camera']['index']}")
                ret, _ = self.camera.read()
                if not ret:
                    raise Exception("Camera initialized but failed to capture test frame")
                
            except Exception as e:
                self.logger.error(f"Error initializing camera: {str(e)}")
                if self.camera is not None:
                    self.camera.release()
                    self.camera = None
                raise

    def take_picture(self, filename: Optional[str] = None) -> Optional[str]:
        """Take a picture and save it to file"""
        with self.lock:
            try:
                if not self.camera or not self.camera.isOpened():
                    self.initialize_camera()

                # Read a frame
                ret, frame = self.camera.read()
                if not ret or frame is None:
                    raise Exception("Failed to capture frame.")

                # Generate filename if not provided
                if filename is None:
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    filename = f"photo_{timestamp}.jpg"

                # Full path for the file
                filepath = os.path.join(self.photos_dir, filename)

                # Save the image
                cv2.imwrite(filepath, frame)
                self.logger.info(f"Picture saved to {filepath}")

                return filepath

            except Exception as e:
                self.logger.error(f"Error taking picture: {str(e)}")
                return None

    def get_preview_frame(self) -> Optional[bytes]:
        """Get a single frame as JPEG bytes for preview"""
        with self.lock:
            try:
                if not self.camera or not self.camera.isOpened():
                    self.initialize_camera()

                ret, frame = self.camera.read()
                if not ret or frame is None:
                    raise Exception("Failed to capture preview frame.")

                # Encode frame as JPEG
                _, buffer = cv2.imencode('.jpg', frame)
                return buffer.tobytes()

            except Exception as e:
                self.logger.error(f"Error getting preview frame: {str(e)}")
                return None

    def adjust_settings(self, brightness: Optional[int] = None, 
                       contrast: Optional[int] = None,
                       saturation: Optional[int] = None,
                       exposure: Optional[int] = None):
        """Adjust camera settings"""
        with self.lock:
            try:
                if not self.camera or not self.camera.isOpened():
                    self.initialize_camera()

                if brightness is not None:
                    self.camera.set(cv2.CAP_PROP_BRIGHTNESS, brightness)
                if contrast is not None:
                    self.camera.set(cv2.CAP_PROP_CONTRAST, contrast)
                if saturation is not None:
                    self.camera.set(cv2.CAP_PROP_SATURATION, saturation)
                if exposure is not None:
                    self.camera.set(cv2.CAP_PROP_EXPOSURE, exposure)

                self.logger.info("Camera settings adjusted")

            except Exception as e:
                self.logger.error(f"Error adjusting camera settings: {str(e)}")

    def get_current_settings(self) -> dict:
        """Get current camera settings"""
        with self.lock:
            try:
                if not self.camera or not self.camera.isOpened():
                    self.initialize_camera()

                settings = {
                    'brightness': self.camera.get(cv2.CAP_PROP_BRIGHTNESS),
                    'contrast': self.camera.get(cv2.CAP_PROP_CONTRAST),
                    'saturation': self.camera.get(cv2.CAP_PROP_SATURATION),
                    'exposure': self.camera.get(cv2.CAP_PROP_EXPOSURE),
                    'resolution': {
                        'width': self.camera.get(cv2.CAP_PROP_FRAME_WIDTH),
                        'height': self.camera.get(cv2.CAP_PROP_FRAME_HEIGHT)
                    }
                }
                return settings

            except Exception as e:
                self.logger.error(f"Error getting camera settings: {str(e)}")
                return {}

    def close(self):
        """Properly close the camera"""
        with self.lock:
            if self.camera is not None:
                self.camera.release()
                self.camera = None
                self.logger.info("Camera released")
                
    def __del__(self):
        """Destructor to ensure camera is properly released"""
        self.close()