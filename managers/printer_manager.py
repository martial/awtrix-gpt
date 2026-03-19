import logging
import os
from typing import Optional

from thermalprinter import ThermalPrinter
from PIL import Image

from config_loader import load_config


class ThermalPrinterManager:
    def __init__(self):
        """Initialize thermal printer manager"""
        self.logger = logging.getLogger(__name__)
        self.config = load_config()
        self.printer: Optional[ThermalPrinter] = None
        self.is_initialized = False

        self.initialize_printer()
        if self.is_initialized:
            self.printer.inverse(False)
        if self.is_initialized:
            self.printer.bold(True)
        if self.is_initialized:
            self.printer.upside_down(True)

    def initialize_printer(self):
        """Initialize the thermal printer with specified settings"""
        try:
            if not os.path.exists(self.config['printer']['port']):
                self.logger.warning(f"Printer port {self.config['printer']['port']} not found. Printer disabled.")
                self.is_initialized = False
                return

            self.printer = ThermalPrinter(
                port=self.config['printer']['port'],
                baudrate=self.config['printer']['baudrate'],
                heat_time=self.config['printer'].get('heat_time', 80),
                heat_dots=self.config['printer'].get('heat_dots', 7),
                heat_interval=self.config['printer'].get('heat_interval', 2)
            )
            self.is_initialized = True
            self.logger.info("Thermal printer initialized")
        except Exception as e:
            self.is_initialized = False
            self.logger.error(f"Error initializing printer: {str(e)}")
            raise

    def print_image(self, image_path: str, max_width: int = 384) -> bool:
        """Print an image from file"""
        try:
            with Image.open(image_path) as img:
                img = img.convert('L')
                ratio = max_width / img.width
                new_height = int(img.height * ratio)
                img = img.resize((max_width, new_height))
                self.printer.image(img)
                self.printer.feed(2)
                return True
        except Exception as e:
            self.logger.error(f"Error printing image: {str(e)}")
            return False

    def print_text(self, text: str, feed=2) -> bool:
        """Print text"""
        try:
            self.printer.out(text)
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
