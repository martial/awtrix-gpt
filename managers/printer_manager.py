from thermalprinter import ThermalPrinter
from PIL import Image
import logging
from typing import Optional
import os
import yaml

class ThermalPrinterManager:
    def __init__(self):
        """Initialize thermal printer manager"""
        self.logger = logging.getLogger(__name__)
        
        # Load configuration
        try:
            with open('config.yaml', 'r') as file:
                self.config = yaml.safe_load(file)
        except Exception as e:
            self.logger.error(f"Error loading config: {str(e)}")
            raise

        self.printer: Optional[ThermalPrinter] = None
        self.initialize_printer()
        ThermalPrinter.inverse(True)
        ThermalPrinter.bold(True)

    def initialize_printer(self):
        """Initialize the thermal printer with specified settings"""
        try:
            self.printer = ThermalPrinter(
                port=self.config['printer']['port'],  # '/dev/ttyUSB0' for example
                baudrate=self.config['printer']['baudrate'],  # 9600 usually
                heat_time=self.config['printer'].get('heat_time', 80),
                heat_dots=self.config['printer'].get('heat_dots', 7),
                heat_interval=self.config['printer'].get('heat_interval', 2)
            )
       
            self.logger.info("Thermal printer initialized")
        except Exception as e:
            self.logger.error(f"Error initializing printer: {str(e)}")
            raise

    def print_image(self, image_path: str, max_width: int = 384) -> bool:
        """Print an image from file"""
        try:
            # Open and convert image
            with Image.open(image_path) as img:
                # Convert to grayscale
                img = img.convert('L')

                ratio = max_width / img.width
                new_height = int(img.height * ratio)
                img = img.resize((max_width, new_height))
                #img = img.rotate(180)
                # Print the image
                self.printer.image(img)
                self.printer.feed(2)  # Feed 2 lines after printing
                
                return True
                
        except Exception as e:
            self.logger.error(f"Error printing image: {str(e)}")
            return False

    def print_text(self, text: str, feed=1) -> bool:
        """Print text"""
        try:    
            
            self.printer.out(text, strike=True, underline=2, upside_down=True, bold=True)
            self.printer.feed(feed)
            return True
        except Exception as e:
            self.logger.error(f"Error printing text: {str(e)}")
            return False

    def test_print(self) -> bool:
        """Print a test page"""
        try:
            self.printer.out("=== Test Print ===")
            self.printer.feed(1)
            self.printer.out("Thermal Printer OK")
            self.printer.feed(2)
            return True
        except Exception as e:
            self.logger.error(f"Error printing test page: {str(e)}")
            return False

    def close(self):
        """Close the printer connection"""
        try:
            if self.printer:
                self.printer.close()
                self.logger.info("Printer connection closed")
        except Exception as e:
            self.logger.error(f"Error closing printer: {str(e)}")