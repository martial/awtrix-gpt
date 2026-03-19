import base64
import io
import json
import logging
import os
import threading
import time
import traceback
import urllib.request
from datetime import datetime
from functools import wraps
from typing import Optional

from dotenv import load_dotenv
from flask import (Flask, jsonify, redirect, render_template, request,
                   send_file, send_from_directory, url_for)
from google import genai
from google.genai import types
from PIL import Image, ImageDraw, ImageFont

from config_loader import load_config, save_config
from managers.display_manager import AwtrixManager
from managers.camera_manager import CameraManager
from managers.printer_manager import ThermalPrinterManager

load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# --- Helper functions ---

def wrap_and_reverse_text(text, max_width=32):
    """Wrap text and reverse the order of lines"""
    paragraphs = text.split('\n')
    all_wrapped_lines = []

    for paragraph in paragraphs:
        words = paragraph.split()
        lines = []
        current_line = []
        current_length = 0

        for word in words:
            word_length = len(word)
            if current_length + word_length + len(current_line) <= max_width:
                current_line.append(word)
                current_length += word_length
            else:
                if current_line:
                    lines.append(' '.join(current_line))
                current_line = [word]
                current_length = word_length

        if current_line:
            lines.append(' '.join(current_line))

        all_wrapped_lines.extend(lines)

    all_wrapped_lines.reverse()
    return '\n'.join(all_wrapped_lines)


def add_text_to_image(image_bytes, poem_text):
    """Add poem text to the bottom of the rotated image with larger text"""
    image = Image.open(io.BytesIO(image_bytes))
    image = image.rotate(180)

    margin = 40
    font_size = 36
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", font_size)
    except Exception:
        font = ImageFont.load_default()

    try:
        bold_font = ImageFont.truetype("DejaVuSans-Bold.ttf", font_size)
    except Exception:
        bold_font = font

    lines = poem_text.split('\n')
    line_spacing = 10
    text_height = len(lines) * (font_size + line_spacing)

    new_height = image.height + text_height + (2 * margin)
    new_image = Image.new('RGB', (image.width, new_height), 'white')
    new_image.paste(image, (0, 0))

    draw = ImageDraw.Draw(new_image)
    y = image.height + margin

    for line in lines:
        text_width = draw.textlength(line, font=bold_font)
        x = (image.width - text_width) // 2
        draw.text((x + 2, y + 2), line, fill='gray', font=bold_font)
        draw.text((x, y), line, fill='black', font=bold_font)
        y += font_size + line_spacing

    img_byte_arr = io.BytesIO()
    new_image.save(img_byte_arr, format='JPEG', quality=95)
    img_byte_arr.seek(0)
    return img_byte_arr.getvalue()


def format_french_timestamp():
    """Format current time as a French timestamp string"""
    current_time = datetime.now()
    french_date = current_time.strftime("%A %d %B %Y").lower()
    french_time = current_time.strftime("%H:%M")

    french_days = {
        'monday': 'lundi', 'tuesday': 'mardi', 'wednesday': 'mercredi',
        'thursday': 'jeudi', 'friday': 'vendredi', 'saturday': 'samedi',
        'sunday': 'dimanche'
    }
    french_months = {
        'january': 'janvier', 'february': 'février', 'march': 'mars',
        'april': 'avril', 'may': 'mai', 'june': 'juin',
        'july': 'juillet', 'august': 'août', 'september': 'septembre',
        'october': 'octobre', 'november': 'novembre', 'december': 'décembre'
    }

    for eng, fr in french_days.items():
        french_date = french_date.replace(eng, fr)
    for eng, fr in french_months.items():
        french_date = french_date.replace(eng, fr)

    return f"{french_date} à {french_time}"


# --- Display Manager wrapper ---

class DisplayManager:
    def __init__(self):
        self.display: Optional[AwtrixManager] = None
        self.display_thread: Optional[threading.Thread] = None
        self.is_running = threading.Event()

    def initialize_display(self, host: str, debug: bool = False):
        """Initialize or reinitialize the display"""
        if self.is_running.is_set():
            self.stop_display()

        self.display = AwtrixManager(host=host, debug=debug)
        self.is_running.set()

        self.display_thread = threading.Thread(target=self.run_display_cycle, daemon=True)
        self.display_thread.start()

        logger.info(f"Display initialized with host: {host}")

    def stop_display(self):
        """Stop the display thread"""
        if self.is_running.is_set():
            self.is_running.clear()
            if self.display_thread:
                self.display_thread.join(timeout=5)

    def run_display_cycle(self):
        """Background thread function for display cycle"""
        logger.info("Starting display cycle thread")

        while self.is_running.is_set():
            try:
                if self.display.should_update_content():
                    self.display.create_daily_poems()
                    self.display.last_update_time = datetime.now()

                self.display.display_cycle()

            except Exception as e:
                logger.error(f"Error in display cycle: {str(e)}")
            finally:
                threading.Event().wait(5)


# --- Flask App ---

def create_app():
    app = Flask(__name__)

    # Create display manager
    display_manager = DisplayManager()

    # Initialize display
    host = os.getenv('AWTRIX_HOST', '192.168.1.101')
    debug = os.getenv('AWTRIX_DEBUG', 'False').lower() == 'true'
    try:
        display_manager.initialize_display(host, debug)
    except Exception as e:
        logger.error(f"Failed to initialize display on startup: {str(e)}")

    def require_api_key(f):
        """Decorator to require API key for routes"""
        @wraps(f)
        def decorated_function(*args, **kwargs):
            api_key = request.headers.get('X-API-Key')
            if not api_key or api_key != os.getenv('API_KEY'):
                return jsonify({'error': 'Invalid API key'}), 401
            return f(*args, **kwargs)
        return decorated_function

    @app.route('/')
    def index():
        return redirect(url_for('config_interface'))

    @app.route('/config')
    def config_interface():
        """Display configuration interface"""
        try:
            config = load_config(force_reload=True)
            available_cameras = camera_manager.list_available_cameras()
            return render_template('config.html',
                                   config=config,
                                   available_cameras=available_cameras)
        except Exception as e:
            logger.error(f"Error loading configuration: {str(e)}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/config/display', methods=['POST'])
    def update_display_config():
        """Update display settings"""
        try:
            config = load_config(force_reload=True)

            config['display']['host'] = request.form['host']
            config['display']['debug'] = 'debug' in request.form
            config['display']['active_hours']['start'] = int(request.form['start_hour'])
            config['display']['active_hours']['end'] = int(request.form['end_hour'])
            config['display']['message_duration'] = int(request.form['message_duration'])

            save_config(config)

            display_manager.initialize_display(
                host=config['display']['host'],
                debug=config['display']['debug']
            )

            return jsonify({
                'status': 'success',
                'message': 'Display settings updated successfully'
            })
        except Exception as e:
            logger.error(f"Error updating display config: {str(e)}")
            return jsonify({'status': 'error', 'message': str(e)}), 500

    @app.route('/api/config/prompt', methods=['GET', 'POST'])
    def manage_prompt_template():
        """Manage prompt template"""
        prompt_path = os.path.join(os.path.dirname(__file__), 'prompt_template.txt')

        if request.method == 'POST':
            try:
                new_template = request.form.get('prompt_template')
                if new_template:
                    with open(prompt_path, 'w', encoding='utf-8') as file:
                        file.write(new_template)

                    if display_manager.display:
                        display_manager.display.prompt_template = new_template

                    return jsonify({
                        'status': 'success',
                        'message': 'Prompt template updated successfully'
                    })
            except Exception as e:
                logger.error(f"Error updating prompt template: {str(e)}")
                return jsonify({'status': 'error', 'message': str(e)}), 500

        # GET request
        try:
            with open(prompt_path, 'r', encoding='utf-8') as file:
                template_content = file.read()
            return jsonify({
                'status': 'success',
                'template': template_content
            })
        except Exception as e:
            logger.error(f"Error reading prompt template: {str(e)}")
            return jsonify({'status': 'error', 'message': str(e)}), 500

    @app.route('/api/config/colors', methods=['POST'])
    def update_color_config():
        """Update color settings"""
        try:
            config = load_config(force_reload=True)

            for category in config['colors'].keys():
                hex_value = request.form.get(f'{category}_hex')
                if hex_value:
                    config['colors'][category] = hex_value

            save_config(config)

            return jsonify({
                'status': 'success',
                'message': 'Colors updated successfully'
            })
        except Exception as e:
            logger.error(f"Error updating color config: {str(e)}")
            return jsonify({'status': 'error', 'message': str(e)}), 500

    @app.route('/api/config/words', methods=['POST'])
    def update_word_config():
        """Update word categories"""
        try:
            config = load_config(force_reload=True)

            for category in config['words'].keys():
                words_text = request.form.get(f'{category}_words', '')
                words_list = [w.strip() for w in words_text.split(',') if w.strip()]
                config['words'][category] = words_list

            save_config(config)

            return jsonify({
                'status': 'success',
                'message': 'Word categories updated successfully'
            })
        except Exception as e:
            logger.error(f"Error updating word config: {str(e)}")
            return jsonify({'status': 'error', 'message': str(e)}), 500

    @app.route('/api/config/weather', methods=['POST'])
    def update_weather_config():
        """Update weather cities"""
        try:
            config = load_config(force_reload=True)

            for city_key in config['weather']['cities'].keys():
                config['weather']['cities'][city_key].update({
                    'name': request.form.get(f'{city_key}_name'),
                    'language': request.form.get(f'{city_key}_language'),
                    'lat': float(request.form.get(f'{city_key}_lat')),
                    'lon': float(request.form.get(f'{city_key}_lon'))
                })

            save_config(config)

            return jsonify({
                'status': 'success',
                'message': 'Weather cities updated successfully'
            })
        except Exception as e:
            logger.error(f"Error updating weather config: {str(e)}")
            return jsonify({'status': 'error', 'message': str(e)}), 500

    @app.route('/api/send', methods=['POST'])
    def send_message():
        """Send a custom message to the display"""
        if not display_manager.display:
            return jsonify({'error': 'Display not initialized'}), 500

        try:
            text = request.json.get('text')
            duration = request.json.get('duration', 15)

            if not text:
                return jsonify({'error': 'Text is required'}), 400

            fragments = display_manager.display.parse_and_highlight(text)
            display_manager.display.display_message(fragments, duration=duration)

            return jsonify({
                'status': 'success',
                'message': 'Message sent successfully',
                'text': text,
                'duration': duration
            })

        except Exception as e:
            logger.error(f"Error sending message: {str(e)}")
            return jsonify({'status': 'error', 'message': str(e)}), 500

    @app.route('/api/status', methods=['GET'])
    def get_status():
        """Get current display status"""
        display = display_manager.display
        thread = display_manager.display_thread

        return jsonify({
            'status': 'success',
            'data': {
                'initialized': display is not None,
                'running': thread.is_alive() if thread else False,
                'last_update': display.last_update_time.isoformat() if display and hasattr(display, 'last_update_time') and display.last_update_time else None,
                'host': display.host if display else None,
                'debug': display.debug if display else None,
                'poems_count': len(display.poems) if display and display.poems else 0,
                'weather_count': len(display.weather) if display and display.weather else 0,
                'messages_count': len(display.messages) if display and display.messages else 0,
                'queue_remaining': len(display.message_queue) if display and display.message_queue else 0
            }
        })

    camera_manager = CameraManager()

    @app.route('/api/config/camera', methods=['POST'])
    def update_camera_config():
        """Update camera settings"""
        try:
            config = load_config(force_reload=True)

            old_index = config['camera']['index']

            config['camera']['index'] = int(request.form['camera_index'])
            config['camera']['name'] = request.form['camera_name']
            config['camera']['resolution']['width'] = int(request.form['resolution_width'])
            config['camera']['resolution']['height'] = int(request.form['resolution_height'])
            config['camera']['settings']['photo_directory'] = request.form['photo_directory']

            save_config(config)

            if old_index != config['camera']['index']:
                camera_manager.close()
                camera_manager.__init__()
            else:
                camera_manager.initialize_camera()

            return jsonify({
                'status': 'success',
                'message': 'Camera settings updated successfully. Please wait for preview to refresh.'
            })
        except Exception as e:
            logger.error(f"Error updating camera config: {str(e)}")
            return jsonify({'status': 'error', 'message': str(e)}), 500

    @app.route('/api/camera/photo', methods=['POST'])
    def take_photo():
        """Take a photo and save it"""
        try:
            filepath = camera_manager.take_picture()
            if filepath:
                return jsonify({
                    'status': 'success',
                    'message': 'Photo taken successfully',
                    'filepath': filepath
                })
            else:
                return jsonify({'status': 'error', 'message': 'Failed to take photo'}), 500
        except Exception as e:
            logger.error(f"Error taking photo: {str(e)}")
            return jsonify({'status': 'error', 'message': str(e)}), 500

    @app.route('/api/camera/preview')
    def get_preview():
        """Get camera preview frame"""
        try:
            original_frame, _ = camera_manager.get_preview_frame()
            if original_frame:
                return send_file(
                    io.BytesIO(original_frame),
                    mimetype='image/jpeg'
                )
            else:
                return jsonify({'status': 'error', 'message': 'Failed to get preview'}), 500
        except Exception as e:
            logger.error(f"Error getting preview: {str(e)}")
            return jsonify({'status': 'error', 'message': str(e)}), 500

    @app.route('/photos/<path:filename>')
    def serve_photo(filename):
        """Serve photos from the photos directory"""
        try:
            return send_from_directory('photos', filename)
        except Exception as e:
            logger.error(f"Error serving photo: {str(e)}")
            return jsonify({'status': 'error', 'message': 'Photo not found'}), 404

    @app.route('/api/camera/settings', methods=['GET', 'POST'])
    def manage_camera_settings():
        """Get or update camera settings"""
        if request.method == 'POST':
            try:
                settings = request.json
                camera_manager.adjust_settings(
                    brightness=settings.get('brightness'),
                    contrast=settings.get('contrast'),
                    saturation=settings.get('saturation'),
                    exposure=settings.get('exposure')
                )
                return jsonify({'status': 'success', 'message': 'Camera settings updated'})
            except Exception as e:
                logger.error(f"Error updating camera settings: {str(e)}")
                return jsonify({'status': 'error', 'message': str(e)}), 500
        else:
            try:
                settings = camera_manager.get_current_settings()
                return jsonify({'status': 'success', 'settings': settings})
            except Exception as e:
                logger.error(f"Error getting camera settings: {str(e)}")
                return jsonify({'status': 'error', 'message': str(e)}), 500

    printer_manager = ThermalPrinterManager()

    @app.route('/api/printer/status', methods=['GET'])
    def get_printer_status():
        """Get printer status"""
        try:
            status = printer_manager.test_print()
            return jsonify({
                'status': 'success' if status else 'error',
                'message': 'Printer is ready' if status else 'Printer not responding'
            })
        except Exception as e:
            logger.error(f"Error getting printer status: {str(e)}")
            return jsonify({'status': 'error', 'message': str(e)}), 500

    @app.route('/api/printer/print', methods=['POST'])
    def print_snapshot():
        """Print the latest snapshot"""
        try:
            image_path = request.json.get('image_path')
            if not image_path:
                return jsonify({'status': 'error', 'message': 'Image path is required'}), 400

            success = printer_manager.print_image(image_path)
            return jsonify({
                'status': 'success' if success else 'error',
                'message': 'Image printed successfully' if success else 'Failed to print image'
            })
        except Exception as e:
            logger.error(f"Error printing image: {str(e)}")
            return jsonify({'status': 'error', 'message': str(e)}), 500

    @app.route('/api/generate_poem_with_photo', methods=['POST', 'GET'])
    def generate_poem_with_photo():
        """Take a photo, generate a poem with Claude AI, and print both."""
        prompt_text = """
        Looking at this photo, analyze the scene and create a response following these rules:

        1. Return a JSON object with three keys:
        - "result": the poem (Italian or French)
        - "description": a scene description in French (max 3 lines of 32 chars) about:
            * Room ambiance and lighting
            * Order/disorder level
            * Presence of people/objects
            * General atmosphere
        - "timestamp": current time in French format (leave this empty, code will fill it)

        Poem rules:
        - Maximum 8 lines
        - Maximum 32 characters per line
        - If there is a man in the picture, refer to him as "Marziol"
        - If there is a woman in the picture, refer to him as "Elisa"
        - You must include persons in the poem.
        - Use \\n for line breaks

        Return exact format:
        {
            "result": "poem here with\\nline breaks",
            "description": "French description here\\nwith line breaks if needed",
            "timestamp": ""
        }

        Do not use markdown or other formatting.
        """

        try:
            config = load_config()

            # Capture a photo
            camera_manager.camera.read()
            time.sleep(0.2)

            original_frame, threshold_frame = camera_manager.get_preview_frame()
            if not original_frame or not threshold_frame:
                return jsonify({'status': 'error', 'message': 'Failed to capture photo'}), 500

            with open("photo.jpg", 'wb') as photo_file:
                photo_file.write(threshold_frame)
            with open("photo_original.jpg", 'wb') as photo_file:
                photo_file.write(original_frame)

            photo_bytes = io.BytesIO(threshold_frame)
            original_bytes = io.BytesIO(original_frame)

            image_data_base64 = base64.b64encode(original_bytes.getvalue()).decode('utf-8')
            image_media_type = 'image/jpeg'

            ai_provider = config.get("ai_provider", "gemini")
            ollama_host = config.get("ollama_host", "http://192.168.1.81:11434")

            if ai_provider == "ollama":
                ollama_url = f"{ollama_host}/api/generate"
                payload = {
                    "model": config.get("ollama_model", "llama3.2"),
                    "prompt": prompt_text,
                    "images": [image_data_base64],
                    "stream": False,
                    "format": "json"
                }
                req = urllib.request.Request(
                    ollama_url,
                    data=json.dumps(payload).encode('utf-8'),
                    headers={'Content-Type': 'application/json'}
                )
                with urllib.request.urlopen(req, timeout=300) as resp:
                    result = json.loads(resp.read().decode('utf-8'))
                    raw_text = result.get("response", "").replace("```json", "").replace("```", "").strip()
            else:
                client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
                image_bytes_decoded = base64.b64decode(image_data_base64)

                contents = [
                    types.Part.from_bytes(data=image_bytes_decoded, mime_type=image_media_type),
                    prompt_text
                ]

                response = client.models.generate_content(
                    model="gemini-3.1-flash-lite-preview",
                    contents=contents,
                )
                raw_text = response.text.replace("```json", "").replace("```", "").strip()

            try:
                response_content = json.loads(raw_text)

                timestamp = format_french_timestamp()
                response_content['timestamp'] = timestamp

                timestamp_formatted = wrap_and_reverse_text(timestamp)
                description_formatted = wrap_and_reverse_text(response_content.get("description", ""))
                poem_formatted = wrap_and_reverse_text(response_content.get("result", ""))

                printer_manager.printer.justify("C")
                printer_manager.printer.bold(False)
                printer_manager.print_text("----------", 2)
                printer_manager.print_image("photo.jpg")
                printer_manager.printer.bold(False)
                printer_manager.printer.justify("L")
                printer_manager.print_text(poem_formatted + "\n", 0)
                printer_manager.print_text(description_formatted + "\n", 0)
                printer_manager.print_text(timestamp_formatted, 0)
                printer_manager.print_text("\n")

                photo_bytes.seek(0)
                processed_image = add_text_to_image(photo_bytes.getvalue(), response_content['result'])

                return send_file(
                    io.BytesIO(processed_image),
                    mimetype='image/jpeg',
                    as_attachment=True,
                    download_name="photo_with_poem.jpg"
                )

            except json.JSONDecodeError as e:
                logger.error(f"Error parsing JSON: {e}, raw text: {raw_text}")
                return jsonify({'status': 'error', 'message': f'JSON parsing error: {str(e)}'}), 500

        except Exception as e:
            logger.error(f"Error in /api/generate_poem_with_photo: {str(e)}")
            logger.error(traceback.format_exc())
            return jsonify({'status': 'error', 'message': str(e)}), 500

    return app


def main():
    try:
        port = int(os.getenv('PORT', 5001))
        debug = os.getenv('FLASK_DEBUG', 'False').lower() == 'true'
        logger.info(f"Starting server on port {port} with debug={debug}")

        app = create_app()
        app.run(host='0.0.0.0', port=port, debug=debug)

    except Exception as e:
        logger.error(f"Server error: {str(e)}")
        raise


if __name__ == '__main__':
    main()
