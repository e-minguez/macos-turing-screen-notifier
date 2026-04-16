import sys
import time
import threading
from typing import Optional

import requests

from config import WeatherConfig

# WMO Weather Interpretation Codes → short human-readable label
WMO_DESCRIPTIONS: dict[int, str] = {
    0:  "Clear",
    1:  "Mostly Clear",
    2:  "Partly Cloudy",
    3:  "Overcast",
    45: "Fog",
    48: "Rime Fog",
    51: "Light Drizzle",
    53: "Drizzle",
    55: "Heavy Drizzle",
    56: "Freezing Drizzle",
    57: "Heavy Freezing Drizzle",
    61: "Light Rain",
    63: "Rain",
    65: "Heavy Rain",
    66: "Freezing Rain",
    67: "Heavy Freezing Rain",
    71: "Light Snow",
    73: "Snow",
    75: "Heavy Snow",
    77: "Snow Grains",
    80: "Rain Showers",
    81: "Rain Showers",
    82: "Heavy Showers",
    85: "Snow Showers",
    86: "Heavy Snow Showers",
    95: "Thunderstorm",
    96: "Thunderstorm",
    99: "Thunderstorm",
}


def _wmo_description(code: int) -> str:
    return WMO_DESCRIPTIONS.get(code, "Unknown")


class WeatherService:
    """Fetches weather from Open-Meteo in a background daemon thread and caches the result."""

    def __init__(self, cfg: WeatherConfig):
        self._cfg = cfg
        self._data: Optional[dict] = None
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="weather")

    def start(self) -> None:
        self._thread.start()

    def get(self) -> Optional[dict]:
        """Thread-safe access to the latest weather data. Returns None until first fetch succeeds."""
        with self._lock:
            return self._data

    def _loop(self) -> None:
        while True:
            try:
                data = self._fetch()
                with self._lock:
                    self._data = data
            except Exception as e:
                print(f"[weather] fetch error: {e}", file=sys.stderr)
            time.sleep(self._cfg.refresh_interval * 60)

    def _fetch(self) -> dict:
        unit_symbol = "°F" if self._cfg.temperature_unit == "fahrenheit" else "°C"
        url = (
            "https://api.open-meteo.com/v1/forecast"
            f"?latitude={self._cfg.latitude}"
            f"&longitude={self._cfg.longitude}"
            "&current=temperature_2m,weather_code,is_day"
            f"&temperature_unit={self._cfg.temperature_unit}"
        )
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        current = resp.json()["current"]
        code = int(current.get("weather_code", 0))
        return {
            "temperature": float(current.get("temperature_2m", 0)),
            "weather_code": code,
            "is_day": int(current.get("is_day", 1)),
            "condition": _wmo_description(code),
            "unit": unit_symbol,
        }
