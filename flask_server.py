from flask import Flask, request, jsonify
import threading
import logging
from typing import Optional
from functools import wraps
import os
from datetime import datetime
from dotenv import load_dotenv
from flask import render_template, request, redirect, url_for, flash, send_from_directory
import yaml
import os
from flask import send_file
import io
from managers.display_manager import AwtrixManager
from managers.camera_manager import CameraManager
from managers.printer_manager import ThermalPrinterManager
from thermalprinter import ThermalPrinter
from anthropic import Anthropic
import base64 
import json
import traceback
import time 

load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class DisplayManager:
    def __init__(self):
        self.display: Optional[AwtrixManager] = None
        self.display_thread: Optional[threading.Thread] = None
        self.is_running = threading.Event()
        
    def initialize_display(self, host: str, debug: bool = False):
        """Initialize or reinitialize the display"""
        # Stop existing display if running
        if self.is_running.is_set():
            self.stop_display()

        # Create new display instance
        self.display = AwtrixManager(host=host, debug=debug)
        self.is_running.set()
        
        # Start display thread
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
            with open('config.yaml', 'r') as file:
                config = yaml.safe_load(file)
            
            # Get list of available cameras
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
            with open('config.yaml', 'r') as file:
                config = yaml.safe_load(file)
            
            # Update display settings
            config['display']['host'] = request.form['host']
            config['display']['debug'] = 'debug' in request.form
            config['display']['active_hours']['start'] = int(request.form['start_hour'])
            config['display']['active_hours']['end'] = int(request.form['end_hour'])
            config['display']['message_duration'] = int(request.form['message_duration'])
            
            # Save updated config
            with open('config.yaml', 'w') as file:
                yaml.dump(config, file, default_flow_style=False)
            
            # Reinitialize display with new settings
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
            return jsonify({
                'status': 'error',
                'message': str(e)
            }), 500

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
                        
                    # Reload the template in the display manager
                    if display_manager.display:
                        display_manager.display.prompt_template = new_template
                    
                    return jsonify({
                        'status': 'success',
                        'message': 'Prompt template updated successfully'
                    })
            except Exception as e:
                logger.error(f"Error updating prompt template: {str(e)}")
                return jsonify({
                    'status': 'error',
                    'message': str(e)
                }), 500
                
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
            return jsonify({
                'status': 'error',
                'message': str(e)
            }), 500

    @app.route('/api/config/colors', methods=['POST'])
    def update_color_config():
        """Update color settings"""
        try:
            with open('config.yaml', 'r') as file:
                config = yaml.safe_load(file)
            
            # Update colors
            for category in config['colors'].keys():
                hex_value = request.form.get(f'{category}_hex')
                if hex_value:
                    config['colors'][category] = hex_value
            
            # Save updated config
            with open('config.yaml', 'w') as file:
                yaml.dump(config, file, default_flow_style=False)
            
            return jsonify({
                'status': 'success',
                'message': 'Colors updated successfully'
            })
        except Exception as e:
            logger.error(f"Error updating color config: {str(e)}")
            return jsonify({
                'status': 'error',
                'message': str(e)
            }), 500

    @app.route('/api/config/words', methods=['POST'])
    def update_word_config():
        """Update word categories"""
        try:
            with open('config.yaml', 'r') as file:
                config = yaml.safe_load(file)
            
            # Update word lists
            for category in config['words'].keys():
                words_text = request.form.get(f'{category}_words', '')
                words_list = [w.strip() for w in words_text.split(',') if w.strip()]
                config['words'][category] = words_list
            
            # Save updated config
            with open('config.yaml', 'w') as file:
                yaml.dump(config, file, default_flow_style=False)
            
            return jsonify({
                'status': 'success',
                'message': 'Word categories updated successfully'
            })
        except Exception as e:
            logger.error(f"Error updating word config: {str(e)}")
            return jsonify({
                'status': 'error',
                'message': str(e)
            }), 500

    @app.route('/api/config/weather', methods=['POST'])
    def update_weather_config():
        """Update weather cities"""
        try:
            with open('config.yaml', 'r') as file:
                config = yaml.safe_load(file)
            
            # Update cities
            for city_key in config['weather']['cities'].keys():
                config['weather']['cities'][city_key].update({
                    'name': request.form.get(f'{city_key}_name'),
                    'language': request.form.get(f'{city_key}_language'),
                    'lat': float(request.form.get(f'{city_key}_lat')),
                    'lon': float(request.form.get(f'{city_key}_lon'))
                })
            
            # Save updated config
            with open('config.yaml', 'w') as file:
                yaml.dump(config, file, default_flow_style=False)
            
            return jsonify({
                'status': 'success',
                'message': 'Weather cities updated successfully'
            })
        except Exception as e:
            logger.error(f"Error updating weather config: {str(e)}")
            return jsonify({
                'status': 'error',
                'message': str(e)
            }), 500

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
            return jsonify({
                'status': 'error',
                'message': str(e)
            }), 500

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
                'last_update': display.last_update_time.isoformat() if display and display.last_update_time else None,
                'host': display.host if display else None,
                'debug': display.debug if display else None,
                'poems_count': len(display.poems) if display and display.poems else 0,
                'weather_phrases_count': len(display.weather_phrases) if display and display.weather_phrases else 0
            }
        })


    camera_manager = CameraManager()

    @app.route('/api/config/camera', methods=['POST'])
    def update_camera_config():
        """Update camera settings"""
        try:
            with open('config.yaml', 'r') as file:
                config = yaml.safe_load(file)
            
            # Store old index to check if it changed
            old_index = config['camera']['index']
            
            # Update camera settings
            config['camera']['index'] = int(request.form['camera_index'])
            config['camera']['name'] = request.form['camera_name']
            config['camera']['resolution']['width'] = int(request.form['resolution_width'])
            config['camera']['resolution']['height'] = int(request.form['resolution_height'])
            config['camera']['settings']['photo_directory'] = request.form['photo_directory']
            
            # Save updated config
            with open('config.yaml', 'w') as file:
                yaml.dump(config, file, default_flow_style=False)
            
            # Force camera reinitialization if index changed
            if old_index != config['camera']['index']:
                camera_manager.close()  # Close existing camera
                camera_manager.__init__()  # Reinitialize with new config
            else:
                # Just update settings if same camera
                camera_manager.initialize_camera()
            
            return jsonify({
                'status': 'success',
                'message': 'Camera settings updated successfully. Please wait for preview to refresh.'
            })
        except Exception as e:
            logger.error(f"Error updating camera config: {str(e)}")
            return jsonify({
                'status': 'error',
                'message': str(e)
            }), 500
    
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
                return jsonify({
                    'status': 'error',
                    'message': 'Failed to take photo'
                }), 500
        except Exception as e:
            logger.error(f"Error taking photo: {str(e)}")
            return jsonify({
                'status': 'error',
                'message': str(e)
            }), 500

    @app.route('/api/camera/preview')
    def get_preview():
        """Get camera preview frame"""
        try:
            frame = camera_manager.get_preview_frame()
            if frame:
                return send_file(
                    io.BytesIO(frame),
                    mimetype='image/jpeg'
                )
            else:
                return jsonify({
                    'status': 'error',
                    'message': 'Failed to get preview'
                }), 500
        except Exception as e:
            logger.error(f"Error getting preview: {str(e)}")
            return jsonify({
                'status': 'error',
                'message': str(e)
            }), 500

    @app.route('/photos/<path:filename>')
    def serve_photo(filename):
        """Serve photos from the photos directory"""
        try:
            return send_from_directory('photos', filename)
        except Exception as e:
            logger.error(f"Error serving photo: {str(e)}")
            return jsonify({
                'status': 'error',
                'message': 'Photo not found'
            }), 404
        
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
                return jsonify({
                    'status': 'success',
                    'message': 'Camera settings updated'
                })
            except Exception as e:
                logger.error(f"Error updating camera settings: {str(e)}")
                return jsonify({
                    'status': 'error',
                    'message': str(e)
                }), 500
        else:
            try:
                settings = camera_manager.get_current_settings()
                return jsonify({
                    'status': 'success',
                    'settings': settings
                })
            except Exception as e:
                logger.error(f"Error getting camera settings: {str(e)}")
                return jsonify({
                    'status': 'error',
                    'message': str(e)
                }), 500
            
    printer_manager = ThermalPrinterManager()

    @app.route('/api/printer/status', methods=['GET'])
    def get_printer_status():
        """Get printer status"""
        try:
            # Test printer connection
            status = printer_manager.test_print()
            return jsonify({
                'status': 'success' if status else 'error',
                'message': 'Printer is ready' if status else 'Printer not responding'
            })
        except Exception as e:
            logger.error(f"Error getting printer status: {str(e)}")
            return jsonify({
                'status': 'error',
                'message': str(e)
            }), 500

    @app.route('/api/printer/print', methods=['POST'])
    def print_snapshot():
        """Print the latest snapshot"""
        try:
            image_path = request.json.get('image_path')
            if not image_path:
                return jsonify({
                    'status': 'error',
                    'message': 'Image path is required'
                }), 400

            success = printer_manager.print_image(image_path)
            return jsonify({
                'status': 'success' if success else 'error',
                'message': 'Image printed successfully' if success else 'Failed to print image'
            })
        except Exception as e:
            logger.error(f"Error printing image: {str(e)}")
            return jsonify({
                'status': 'error',
                'message': str(e)
            }), 500
    
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
        – You must include persons in the poem.
        - Use \\n for line breaks
        
        Return exact format:
        {
            "result": "poem here with\\nline breaks",
            "description": "French description here\\nwith line breaks if needed",
            "timestamp": ""
        }

        Do not use markdown or other formatting.
        """

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
                            line = ' '.join(current_line)
                            lines.append(line)
                        current_line = [word]
                        current_length = word_length

                if current_line:
                    line = ' '.join(current_line)
                    lines.append(line)

                all_wrapped_lines.extend(lines)

            all_wrapped_lines.reverse()
            return '\n'.join(all_wrapped_lines)

        def add_text_to_image(image_bytes, poem_text):
            """Add poem text to the bottom of the rotated image with larger text"""
            from PIL import Image, ImageDraw, ImageFont
            import io

            # Open the image
            image = Image.open(io.BytesIO(image_bytes))
            
            # Rotate the image 180 degrees
            image = image.rotate(180)
            
            # Calculate the space needed for text
            margin = 40  # Increased margin for better spacing
            font_size = 36  # Increased font size
            try:
                font = ImageFont.truetype("DejaVuSans.ttf", font_size)
            except:
                font = ImageFont.load_default()
                
            # Calculate text height
            lines = poem_text.split('\n')
            line_spacing = 10  # Increased line spacing
            text_height = len(lines) * (font_size + line_spacing)
            
            # Create new image with extra space for text
            new_height = image.height + text_height + (2 * margin)
            new_image = Image.new('RGB', (image.width, new_height), 'white')
            
            # Paste the rotated original image
            new_image.paste(image, (0, 0))
            
            # Add text
            draw = ImageDraw.Draw(new_image)
            y = image.height + margin
            
            # Try to load a bold version of the font for better visibility
            try:
                bold_font = ImageFont.truetype("DejaVuSans-Bold.ttf", font_size)
            except:
                bold_font = font
            
            for line in lines:
                # Center the text
                text_width = draw.textlength(line, font=bold_font)
                x = (image.width - text_width) // 2
                # Draw with a light shadow for better readability
                draw.text((x+2, y+2), line, fill='gray', font=bold_font)  # Shadow
                draw.text((x, y), line, fill='black', font=bold_font)  # Main text
                y += font_size + line_spacing

            # Convert back to bytes
            img_byte_arr = io.BytesIO()
            new_image.save(img_byte_arr, format='JPEG', quality=95)  # Increased quality
            img_byte_arr.seek(0)
            
            return img_byte_arr.getvalue()

        try:
            # Capture a photo
            camera_manager.camera.read()  # Clear any stale frame
            time.sleep(0.2)  # Small delay to ensure fresh frame
            
            # Capture a photo
            original_frame, threshold_frame = camera_manager.get_preview_frame()
            if not original_frame or not threshold_frame:
                return jsonify({'status': 'error', 'message': 'Failed to capture photo'}), 500

            # Save both images
            with open("photo.jpg", 'wb') as photo_file:
                photo_file.write(threshold_frame)  # Save thresholded version for printing
                
            with open("photo_original.jpg", 'wb') as photo_file:
                photo_file.write(original_frame)  # Save original for reference

            # Create bytes objects for both images
            photo_bytes = io.BytesIO(threshold_frame)
            original_bytes = io.BytesIO(original_frame)

            image_data_base64 = base64.b64encode(original_bytes.getvalue()).decode('utf-8')
            image_media_type = 'image/jpeg'

            # Prepare the messages payload
            messages = [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": image_media_type,
                                "data": image_data_base64,
                            },
                        },
                        {
                            "type": "text",
                            "text": prompt_text
                        }
                    ]
                }
            ]
            anthropic = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

            response = anthropic.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=1024,
                messages=messages
            )

            # Extract and parse response
            raw_text = response.content[0].text.strip()
            
            try:
                # Parse the JSON response
                response_content = json.loads(raw_text)
                
                # Add timestamp in French format
                current_time = datetime.now()
                french_date = current_time.strftime("%A %d %B %Y").lower()
                french_time = current_time.strftime("%H:%M")
                
                # Translate day and month to French
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
                
                timestamp = f"{french_date} à {french_time}"
                response_content['timestamp'] = timestamp
                
                # Wrap and reverse all text content
                timestamp_formatted = wrap_and_reverse_text(timestamp)
                description_formatted = wrap_and_reverse_text(response_content.get("description", ""))
                poem_formatted = wrap_and_reverse_text(response_content.get("result", ""))
                
                # Print everything
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

                # Process the image with the poem
                photo_bytes.seek(0)
                processed_image = add_text_to_image(photo_bytes.getvalue(), response_content['result'])

                # Send processed photo back to user
                return send_file(
                    io.BytesIO(processed_image),
                    mimetype='image/jpeg',
                    as_attachment=True,
                    download_name="photo_with_poem.jpg"
                )

            except json.JSONDecodeError as e:
                print(f"Error parsing JSON: {e}")
                print(f"Raw text was: {raw_text}")
                return jsonify({'status': 'error', 'message': f'JSON parsing error: {str(e)}'}), 500

        except Exception as e:
            logging.error(f"Error in /api/generate_poem_with_photo: {str(e)}")
            logging.error("Error in /api/generate_poem_with_photo")
            logging.error(traceback.format_exc())
            return jsonify({'status': 'error', 'message': str(e)}), 500
    
    return app

def main():
    try:
        port = int(os.getenv('PORT', 5001))
        debug = os.getenv('FLASK_DEBUG', 'False').lower() == 'true'
        print(f"Starting server on port {port} with debug={debug}")
        
        app = create_app()
        app.run(host='0.0.0.0', port=port, debug=debug)
        
    except Exception as e:
        logger.error(f"Server error: {str(e)}")
        raise

if __name__ == '__main__':
    main()