import re
import requests
import time
from google import genai
from google.genai import types
from dotenv import load_dotenv
import os
from datetime import date
from typing import Dict, Optional, List, Any
import json
import random
import math
import colorsys
from datetime import datetime, timedelta
import logging
import yaml
import feedparser

def load_config(config_path: str = None) -> Dict[str, Any]:
    """Load configuration from YAML file"""
    if config_path is None:
        config_path = os.path.join(os.path.dirname(__file__), '../config.yaml')
    
    with open(config_path, 'r', encoding='utf-8') as file:
        return yaml.safe_load(file)

class AwtrixManager:
    def __init__(self, config_path: str = None, host: str = None, debug: bool = None):
        """Initialize AWTRIX display controller"""
        # Set up logging
        logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s', force=True)
        self.logger = logging.getLogger(__name__)
        
        # Load configuration
        self.config = load_config(config_path)
        
        # Override config with constructor parameters if provided
        self.host = host or self.config['display']['host']
        self.debug = debug if debug is not None else self.config['display']['debug']
        
        load_dotenv()
        self.base_url = f"http://{self.host}/api"
        
        # API keys
        self.openweather_api_key = os.getenv('OPENWEATHER_API_KEY')
        self.anthropic_api_key = os.getenv('ANTHROPIC_API_KEY')
        self.news_api_key = os.getenv('NEWS_API_KEY')  # Added news API key
        
        self.ai_provider = self.config.get("ai_provider", "gemini")
        self.ollama_host = self.config.get("ollama_host", "http://192.168.1.81:11434")
        if self.ai_provider == "gemini":
            self.client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
        
        # Load prompt template
        self.prompt_template = self.load_prompt_template()
        
        # City coordinates from config
        self.cities = self.config['weather']['cities']
        
        # Update stored content attributes
        self.messages: Optional[List[Dict[str, str]]] = None
        self.weather: Optional[List[Dict[str, str]]] = None
        self.news: Optional[List[Dict[str, str]]] = None
        self.suggested_activities: Optional[List[Dict[str, str]]] = None
        self.poems: Optional[List[Dict[str, str]]] = None
        self.content_date: Optional[date] = None
        
        # Add rate limiting parameters
        self.last_weather_call = datetime.min
        self.last_news_call = datetime.min
        self.weather_rate_limit = timedelta(minutes=10)  # Minimum time between weather API calls
        self.news_rate_limit = timedelta(minutes=15)     # Minimum time between news API calls
        self.message_queue = []
        self.raw_weather = {}
        
        self.logger.info(f"Initialized AWTRIX controller for {self.host}")

    def load_prompt_template(self) -> str:
        """Load the prompt template from file"""
        try:
            prompt_path = os.path.join(os.path.dirname(__file__), '../prompt_template.txt')
            with open(prompt_path, 'r', encoding='utf-8') as file:
                return file.read()
        except Exception as e:
            self.logger.error(f"Error loading prompt template: {str(e)}")
            raise

    def display_message(self, text_fragments: List[Dict[str, str]], duration: int = None):
        """Display colorized message on AWTRIX with configured duration"""
        try:
            duration = duration or self.config['display']['message_duration']
            payload = {
                "text": text_fragments,
                "repeat": 1,
                "duration": duration
            }
            
            response = requests.post(f"{self.base_url}/notify", json=payload, timeout=10)
            response.raise_for_status()
            time.sleep(duration)
            
        except Exception as e:
            self.logger.error(f"Display error: {str(e)}")


    def draw_liquid_animation(self, duration_sec: int = 5):
        """Draw a liquid animation using vertical HTTP line draws (stable on 0.98 firmware)."""
        try:
            start_time = time.time()
            fps = 2
            t = 0.0
            
            # Simple fallback temp
            temperature = 20
            try:
                if getattr(self, 'weather', None) and len(self.weather) > 0:
                    temp_str = self.weather[0].get('text', '')
                    nums = [int(s) for s in temp_str.split() if s.isdigit()]
                    if nums:
                        temperature = nums[0]
            except Exception:
                pass
                
            # Get wind speed for Marseille to calculate wave height (swell/houle)
            wind_speed = 2.0 # Default fallback
            try:
                marseille_weather = self.raw_weather.get('MARSEILLE', {})
                if marseille_weather and 'wind_speed' in marseille_weather:
                    wind_speed = float(marseille_weather['wind_speed'])
            except Exception:
                pass
                
            # Hue mapping: 0C -> blue (0.6), 35C -> red/orange (0.05)
            base_hue = 0.6 - (max(min(temperature, 35), 0) / 35.0) * 0.55
            
            # Map wind speed (0 to 10+ m/s) to an amplitude multiplier (0.5 to 3.5)
            amplitude = max(0.5, min((wind_speed / 10.0) * 3.0 + 0.5, 3.5))
            # Also increase wave frequency slightly with wind
            freq_mult = max(1.0, min(1.0 + (wind_speed / 20.0), 2.0))
            
            while time.time() - start_time < duration_sec:
                draw_instructions = []
                
                for x in range(32):
                    # Higher wind = faster and taller waves
                    val = math.sin(x * 0.3 * freq_mult + t * 2.0 * freq_mult)
                    
                    # Base water level is 2, plus amplitude
                    wave_height = int((val + 1) * amplitude) + 2
                    
                    # Cap wave height to not exceed screen height (8)
                    wave_height = max(1, min(wave_height, 8))
                    
                    hue = (base_hue + (math.sin(x * 0.1 + t) * 0.05)) % 1.0
                    r, g, b = colorsys.hsv_to_rgb(hue, 1.0, 1.0)
                    hex_color = f"#{int(r*255):02X}{int(g*255):02X}{int(b*255):02X}"
                    
                    draw_instructions.append({"dl": [x, 7, x, 8 - wave_height, hex_color]})
                
                payload = {
                    "draw": draw_instructions
                }
                
                try:
                    requests.post(f"{self.base_url}/custom?name=liquid", json=payload, timeout=0.5)
                except Exception:
                    pass
                    
                t += 0.5
                time.sleep(1.0 / fps)
                
            # Release the screen gracefully by sending an empty string to custom
            requests.post(f"{self.base_url}/custom?name=liquid", json={"text": ""}, timeout=1)
            time.sleep(0.5)
        except Exception as e:
            self.logger.error(f"HTTP liquid error: {e}")

    def get_sea_temperature(self, lat=43.2965, lon=5.3698):
        """Fetch real-time sea temperature using Open-Meteo Marine API."""
        try:
            url = f"https://marine-api.open-meteo.com/v1/marine?latitude={lat}&longitude={lon}&current=ocean_temperature"
            response = requests.get(url, timeout=5)
            if response.status_code == 200:
                data = response.json()
                if 'current' in data and 'ocean_temperature' in data['current']:
                    return data['current']['ocean_temperature']
        except Exception as e:
            self.logger.error(f"Failed to fetch sea temperature: {e}")
        return None

    def get_sea_data(self, lat=43.25, lon=5.37):
        """Fetch real-time wave height, direction, and period using Open-Meteo Marine API."""
        try:
            url = f"https://marine-api.open-meteo.com/v1/marine?latitude={lat}&longitude={lon}&hourly=wave_height,wave_direction,wave_period"
            response = requests.get(url, timeout=5)
            if response.status_code == 200:
                data = response.json()
                if 'hourly' in data and 'wave_height' in data['hourly']:
                    import datetime
                    current_hour = datetime.datetime.now().hour
                    return {
                        'height': data['hourly']['wave_height'][current_hour],
                        'direction': data['hourly']['wave_direction'][current_hour],
                        'period': data['hourly']['wave_period'][current_hour]
                    }
        except Exception as e:
            self.logger.error(f"Failed to fetch sea data: {e}")
        return None

    def get_weather(self) -> Dict[str, Dict]:
        """Fetches detailed weather data for configured cities with rate limiting."""
        # Check rate limit
        now = datetime.now()
        if (now - self.last_weather_call) < self.weather_rate_limit:
            self.logger.debug("Skipping weather update due to rate limit")
            return {}

        weather_data = {}
        for city_key, city_info in self.cities.items():
            try:
                url = "https://api.openweathermap.org/data/2.5/weather"
                params = {
                    'lat': city_info['lat'],
                    'lon': city_info['lon'],
                    'appid': self.openweather_api_key,
                    'units': 'metric',
                    'lang': city_info.get('language', 'en')
                }
                
                response = requests.get(url, params=params, timeout=10)
                response.raise_for_status()
                data = response.json()
                
                weather_data[city_key] = {
                    'temp': round(data['main']['temp']),
                    'feels_like': round(data['main']['feels_like']),
                    'temp_max': round(data['main']['temp_max']),
                    'temp_min': round(data['main']['temp_min']),
                    'humidity': data['main']['humidity'],
                    'wind_speed': data['wind']['speed'],
                    'wind_direction': data['wind']['deg'],
                    'visibility': data.get('visibility', 'N/A'),
                    'pressure': data['main']['pressure'],
                    'cloudiness': data['clouds']['all'],
                    'description': data['weather'][0]['description']
                }
                self.logger.debug(f"Weather data fetched for {city_key}: {weather_data[city_key]}")
                
            except Exception as e:
                self.logger.error(f"Weather error for {city_key}: {str(e)}")
                weather_data[city_key] = None
        
        self.last_weather_call = now
        self.raw_weather = weather_data
        return weather_data
    
    def format_weather_data(self, weather: Dict) -> str:
        """Format weather data for prompt template"""
        if not weather:
            return "data unavailable"
            
        return (f"{weather.get('temp', '??')}°C, feels like {weather.get('feels_like', '??')}°C, "
                f"max {weather.get('temp_max', '??')}°C and min {weather.get('temp_min', '??')}°C. "
                f"Humidity: {weather.get('humidity', '??')}%, wind: {weather.get('wind_speed', '??')} m/s "
                f"from {weather.get('wind_direction', '??')}°, visibility: {weather.get('visibility', 'N/A')} m, "
                f"cloudiness: {weather.get('cloudiness', '??')}%, pressure: {weather.get('pressure', '??')} hPa")

    def get_french_news(self):
        """Fetch current French news headlines and descriptions using top-headlines endpoint"""
        try:
            if self.news_api_key:
                url = "https://newsapi.org/v2/top-headlines"
                params = {
                    'country': 'fr',  # French news
                    'apiKey': self.news_api_key,
                    'pageSize': 5  # Limit to top 5 headlines
                }
                
                response = requests.get(url, params=params, timeout=10)
                print("FRENCH NEWS STATUS:", response.status_code)
                data = response.json()
                
                if data.get('articles'):
                    news_items = []
                    for article in data['articles']:
                        title = article.get('title', '').split('|')[0].split('-')[0].strip()
                        description = article.get('description', '').strip()
                        
                        # Only add if we have both title and description
                        if title and description and len(title) < 100:
                            news_item = f"{title}\n{description}"
                            news_items.append(news_item)
                    
                    if news_items:
                        return "\n\n".join(news_items[:3])  # Limit to 3 most relevant with double newline separation

            # Fallback to RSS feeds if NewsAPI fails
            rss_feeds = [
                "https://www.lemonde.fr/rss/une.xml",
                "https://www.lefigaro.fr/rss/figaro_actualites.xml",
                "https://www.lexpress.fr/rss/alaune.xml"
            ]
            
            for feed_url in rss_feeds:
                try:
                    feed = feedparser.parse(feed_url)
                    if feed.entries:
                        news_items = []
                        for entry in feed.entries[:3]:
                            title = entry.title.split('|')[0].strip()
                            description = getattr(entry, 'description', '').strip()
                            if title and description:
                                news_item = f"{title}\n{description}"
                                news_items.append(news_item)
                        if news_items:
                            return "\n\n".join(news_items)
                except Exception as e:
                    self.logger.warning(f"Error fetching from {feed_url}: {str(e)}")
                    continue

            return "La vie continue en France"  # Generic fallback message

        except Exception as e:
            self.logger.error(f"Error fetching French news: {str(e)}")
            return "Les actualites francaises"
    
    def parse_and_highlight(self, text: str) -> List[Dict[str, str]]:
        """Parse text to highlight based on configuration"""
        fragments = []
        words = re.split(r'(\W+)', text)  # Split by non-word characters to preserve punctuation

        for word in words:
            lower_word = word.lower()
            
            # Check each word category from config
            color_assigned = False
            for category, word_list in self.config['words'].items():
                if lower_word in [w.lower() for w in word_list]:
                    fragments.append({
                        "t": word,
                        "c": self.config['colors'][category]
                    })
                    color_assigned = True
                    break
            
            # Numbers
            if not color_assigned and re.match(r'\d+', word):
                fragments.append({
                    "t": word,
                    "c": self.config['colors']['numbers']
                })
            # Default color for other text
            elif not color_assigned:
                fragments.append({
                    "t": word,
                    "c": self.config['colors']['default']
                })

        return fragments

    def create_daily_poems(self):
        """Create new content if needed"""
        try:
            # Get current weather
            weather = self.get_weather()
            marseille_weather = self.format_weather_data(weather.get('MARSEILLE', {}))
            amantea_weather = self.format_weather_data(weather.get('AMANTEA', {}))

            # Get French news headlines
            french_news = self.get_french_news()
           
            # Get today's day and month in configured languages
            today = datetime.now()
            
            # Format timestamp as a readable date/time string
            timestamp = today.strftime("%d %B %Y %H:%M")

            # Format the prompt with current data
            prompt = self.prompt_template.format(
                timestamp=timestamp,
                marseille_weather=marseille_weather,
                amantea_weather=amantea_weather,
                french_news=french_news
            )

            print(prompt)
            
            if self.ai_provider == "ollama":
                import urllib.request
                import json
                ollama_url = f"{self.ollama_host}/api/generate"
                payload = {
                    "model": self.config.get("ollama_model", "llama3.2"),
                    "prompt": prompt,
                    "stream": False,
                    "format": "json"
                }
                req = urllib.request.Request(ollama_url, data=json.dumps(payload).encode('utf-8'), headers={'Content-Type': 'application/json'})
                with urllib.request.urlopen(req, timeout=120) as resp:
                    result = json.loads(resp.read().decode('utf-8'))
                    raw_text = result.get("response", "").replace("```json", "").replace("```", "").strip()
            else:
                response = self.client.models.generate_content(
                    model="gemini-3.1-flash-lite-preview", 
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        tools=[{"google_search": {}}]
                    )
                )
                raw_text = response.text.replace("```json", "").replace("```", "").strip()

            # Parse JSON response
            data = json.loads(raw_text)
            print(data)
            # Convert simple strings to dictionaries with id and text fields
            def format_messages(messages, prefix):
                return [
                    {"id": f"{prefix}_{i}", "text": msg} 
                    for i, msg in enumerate(messages)
                ]

            self.messages = format_messages(data.get("messages", []), "MSG")
            self.weather = format_messages(data.get("weather", []), "WTH")
            self.news = format_messages(data.get("news", []), "NEWS")
            self.suggested_activities = format_messages(data.get("suggested_activities", []), "ACT")
            self.poems = format_messages(data.get("poems", []), "POEM")
            self.content_date = date.today()
            
            self.logger.info(f"Generated new content: {len(self.messages)} messages, {len(self.weather)} weather, "
                            f"{len(self.news)} news, {len(self.suggested_activities)} activities, {len(self.poems)} poems")
            
        except Exception as e:
            self.logger.error(f"Error creating content: {str(e)}")
            self._set_fallback_content()

    def _set_fallback_content(self):
        """Set fallback content in case of errors"""
        self.messages = [{"id": "M1", "text": "Elisa et Marziol, amoureux des petites joies"}]
        self.weather = [{"id": "W1", "text": "Il fait doux a Marseille et ensoleille a Amantea"}]
        self.news = [{"id": "N1", "text": "Les actualites du jour"}]
        self.suggested_activities = [{"id": "A1", "text": "Un petit smoothie ensemble?"}]
        self.poems = [{"id": "P1", "text": "Marseille Amantea, deux coeurs unis"}]

    def display_cycle(self):
        """Display messages sequentially from a shuffled queue for better flow"""
        if not any([self.messages, self.weather, self.news, self.suggested_activities, self.poems]):
            self.logger.warning("No content available for display")
            return
            
        try:
            # If queue is empty, refill and shuffle it
            if not getattr(self, 'message_queue', None):
                self.message_queue = (self.messages + self.weather + self.news + 
                                     self.suggested_activities + self.poems)
                random.shuffle(self.message_queue)
                
            # Pop the next message from the queue
            item = self.message_queue.pop(0)
            text = item.get("text", "")
            
            self.logger.debug(f"Displaying ({len(self.message_queue)} remaining in queue): {text}")
            fragments = self.parse_and_highlight(text)
            self.display_message(fragments)
            time.sleep(self.config['display']['cycle_delay'])
            
            # Show current temp & sea data before liquid animation
            try:
                marseille_weather = getattr(self, 'raw_weather', {}).get('MARSEILLE', {})
                if marseille_weather:
                    temp = int(marseille_weather.get('temp', 20))
                    # Note: OpenWeatherMap standard endpoint doesn't give sea temperature.
                    # As a funny estimate for the Mediterranean, we'll approximate based on air temp & month,
                    # or just show the air temp for now.
                    sea_temp = max(13, min(26, temp - 2)) # Very rough approximation
                    
                    msg = f"Marseille: {temp}C | Eau: ~{sea_temp}C"
                    fragments = self.parse_and_highlight(msg)
                    self.display_message(fragments, duration=4)
                    time.sleep(4)
            except Exception as e:
                pass
                
            # Show Generative Liquid Animation matching the current temperature
            self.draw_liquid_animation(duration_sec=6)
            
        except Exception as e:
            self.logger.error(f"Error in display cycle: {str(e)}")

    def should_update_content(self) -> bool:
        """Determine if content should be updated based on configuration"""
        current_time = datetime.now()
        current_hour = current_time.hour

        # Check if we're within active hours
        start_hour = self.config['display']['active_hours']['start']
        end_hour = self.config['display']['active_hours']['end']
        if not (start_hour <= current_hour <= end_hour):
            self.logger.debug(f"Outside active hours ({start_hour}:00 - {end_hour}:00)")
            return False

        # Check update interval
        update_interval = timedelta(seconds=self.config['display']['update_interval'])
        if not hasattr(self, 'last_update_time') or not self.last_update_time or (current_time - self.last_update_time) >= update_interval:
            self.logger.info("Time to update content")
            return True

        self.logger.debug(f"Last update was {(current_time - self.last_update_time).seconds / 3600:.2f} hours ago")
        return False

def run_display(config_path: str = None):
    logging.info("Starting AWTRIX Family Weather Poetry Display")
    
    try:
        awtrix = AwtrixManager(config_path=config_path)
        awtrix.last_update_time = None
        
        while True:
            try:
                # Check if we should update content
                if awtrix.should_update_content():
                    awtrix.create_daily_poems()
                    awtrix.last_update_time = datetime.now()
                    logging.info(f"Content updated at {awtrix.last_update_time}")
                
                # Run the display cycle
                awtrix.display_cycle()
                # Add a small delay to prevent CPU overuse
                time.sleep(awtrix.config['display']['cycle_delay'])
                
            except Exception as e:
                logging.error(f"Error in main loop: {str(e)}")
                time.sleep(60)  # Wait a minute before retrying on error

    except KeyboardInterrupt:
        logging.info("\nDisplay stopped by user")
    except Exception as e:
        logging.error(f"\nFatal error: {str(e)}")

if __name__ == "__main__":
    run_display()