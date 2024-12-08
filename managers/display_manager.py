import re
import requests
import time
from anthropic import Anthropic
from dotenv import load_dotenv
import os
from datetime import date
from typing import Dict, Optional, List, Any
import json
import random
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
        
        # Initialize Claude
        self.claude = Anthropic(api_key=self.anthropic_api_key)
        
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
            lyon_weather = self.format_weather_data(weather.get('LYON', {}))
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
                lyon_weather=lyon_weather,
                amantea_weather=amantea_weather,
                french_news=french_news
            )

            print(prompt)
            response = self.claude.messages.create(
                model="claude-3-5-sonnet-latest",
                max_tokens=2000,
                messages=[{"role": "user", "content": prompt}]
            )

            # Parse JSON response
            data = json.loads(response.content[0].text.strip())
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
        self.weather = [{"id": "W1", "text": "Il fait doux a Lyon et ensoleille a Amantea"}]
        self.news = [{"id": "N1", "text": "Les actualites du jour"}]
        self.suggested_activities = [{"id": "A1", "text": "Un petit smoothie ensemble?"}]
        self.poems = [{"id": "P1", "text": "Lyon Amantea, deux coeurs unis"}]

    def display_cycle(self):
        """Display messages with configured delay"""
        if not all([self.messages, self.weather, self.news, self.suggested_activities, self.poems]):
            self.logger.warning("No content available for display")
            return

        # Combine all content types
        all_content = (self.messages + self.weather + self.news + 
                      self.suggested_activities + self.poems)
        
        try:
            item = random.choice(all_content)
            text = item.get("text", "")
            self.logger.debug(f"Displaying: {text}")
            fragments = self.parse_and_highlight(text)
            self.display_message(fragments)
            time.sleep(self.config['display']['cycle_delay'])
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