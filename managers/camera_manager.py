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
        self.is_initialized = False  # Flag to track initialization status
        
        # Create photos directory
        self.photos_dir = os.path.join(os.path.dirname(__file__), 
                                     self.config['camera']['settings']['photo_directory'])
        os.makedirs(self.photos_dir, exist_ok=True)
        
        # Initialize camera
        self.initialize_camera()

    def initialize_camera(self):
        """Initialize the camera with specified settings"""
        with self.lock:
            if self.is_initialized:
                self.logger.info("Camera is already initialized.")
                return  # Avoid reinitializing if already done
            
            try:
                if self.camera is not None:
                    self.camera.release()
                
                # Initialize new camera
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
                
                self.is_initialized = True  # Set the flag to True after successful initialization
                
            except Exception as e:
                self.logger.error(f"Error initializing camera: {str(e)}")
                if self.camera is not None:
                    self.camera.release()
                    self.camera = None
                self.is_initialized = False  # Reset flag on failure
                raise

    def take_picture(self, filename: Optional[str] = None) -> Optional[str]:
        """Take a picture and save it to file"""
        with self.lock:
            try:
                if not self.is_initialized:
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

        # In camera_manager.py (CameraManager class)
    def get_preview_frame(self) -> Optional[bytes]:
        """Get a single frame as JPEG bytes for preview"""
        with self.lock:
            try:
                if not self.is_initialized:
                    self.initialize_camera()

                # Add buffer clearing loop
                for _ in range(5):  # Flush the buffer by reading a few frames
                    self.camera.read()
                    
                ret, frame = self.camera.read()
                if not ret or frame is None:
                    raise Exception("Failed to capture preview frame.")

                frame = cv2.rotate(frame, cv2.ROTATE_180)
                # Convert to grayscale
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                
                # Apply Gaussian blur to reduce noise
                blurred = cv2.GaussianBlur(gray, (5, 5), 0)
                
                # Apply adaptive thresholding
                # We use a large block size (51) and a small constant (2) to get good contrast
                threshold = cv2.adaptiveThreshold(
                    blurred,
                    255,
                    cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                    cv2.THRESH_BINARY,
                    51,  # block size - must be odd number
                    2    # constant subtracted from mean
                )
                
                # Save original and processed images for debugging
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                debug_dir = os.path.join(self.photos_dir, 'debug')
                os.makedirs(debug_dir, exist_ok=True)
                
                # Save original
                original_path = os.path.join(debug_dir, f'original_{timestamp}.jpg')
                cv2.imwrite(original_path, frame)
                
                # Save thresholded
                threshold_path = os.path.join(debug_dir, f'threshold_{timestamp}.jpg')
                cv2.imwrite(threshold_path, threshold)
                
                # Log the paths for debugging
                self.logger.info(f"Saved debug images: \nOriginal: {original_path}\nThreshold: {threshold_path}")

                # Encode thresholded frame as JPEG
                _, buffer = cv2.imencode('.jpg', threshold)
                _, original_buffer = cv2.imencode('.jpg', frame)
                
                return original_buffer.tobytes(), buffer.tobytes()

            except Exception as e:
                self.logger.error(f"Error getting preview frame: {str(e)}")
                return None

    def close(self):
        """Properly close the camera"""
        with self.lock:
            if self.camera is not None:
                self.camera.release()
                self.camera = None
                self.is_initialized = False  # Reset flag when camera is released
                self.logger.info("Camera released")
                
    def __del__(self):
        """Destructor to ensure camera is properly released"""
        self.close()