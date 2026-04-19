import logging
from dataclasses import dataclass
from datetime import datetime, timezone

import requests

from config import STADIUM_COORDS

log = logging.getLogger(__name__)

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

WMO_CODES = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Depositing rime fog",
    51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle",
    61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
    71: "Slight snow", 73: "Moderate snow", 75: "Heavy snow",
    80: "Slight showers", 81: "Moderate showers", 82: "Violent showers",
    95: "Thunderstorm", 96: "Thunderstorm w/ hail", 99: "Thunderstorm w/ heavy hail",
}


@dataclass
class WeatherResult:
    temp_f: float
    conditions: str
    wind_mph: float
    precip_pct: int


def get_game_weather(team_name: str, game_start_utc: datetime) -> WeatherResult | None:
    coords = STADIUM_COORDS.get(team_name)
    if not coords:
        return None

    lat, lon = coords
    try:
        resp = requests.get(
            OPEN_METEO_URL,
            params={
                "latitude": lat,
                "longitude": lon,
                "hourly": "temperature_2m,precipitation_probability,windspeed_10m,weathercode",
                "temperature_unit": "fahrenheit",
                "wind_speed_unit": "mph",
                "timezone": "auto",
                "forecast_days": 3,
            },
            timeout=10,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        log.warning("Weather fetch failed for %s: %s", team_name, exc)
        return None

    data = resp.json()
    hourly = data.get("hourly", {})
    times = hourly.get("time", [])
    temps = hourly.get("temperature_2m", [])
    precips = hourly.get("precipitation_probability", [])
    winds = hourly.get("windspeed_10m", [])
    codes = hourly.get("weathercode", [])

    # Match the hour closest to game start
    game_hour = game_start_utc.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:00")
    # Open-Meteo returns local times; try direct match first, then find closest
    idx = None
    for i, t in enumerate(times):
        if t.startswith(game_start_utc.strftime("%Y-%m-%dT%H")):
            idx = i
            break

    if idx is None:
        log.warning("No weather data found for game hour %s at %s", game_hour, team_name)
        return None

    code = int(codes[idx]) if idx < len(codes) else 0
    return WeatherResult(
        temp_f=round(temps[idx], 1) if idx < len(temps) else 0,
        conditions=WMO_CODES.get(code, "Unknown"),
        wind_mph=round(winds[idx], 1) if idx < len(winds) else 0,
        precip_pct=int(precips[idx]) if idx < len(precips) else 0,
    )
