"""Weather for a place and time: Open-Meteo (free, no key), with a stub when it can't be reached."""
import json
import os
import urllib.parse
import urllib.request
from datetime import datetime

TIMEOUT_S = 3
STUB = {"rain_prob": 70, "temp_c": 12.0, "source": "stub"}  # rainy on purpose: the demo drops the picnic
RAINY = 50  # rain_prob above this rules out outdoor venues

_cache: dict[tuple, dict] = {}


def forecast(lat: float, lng: float, when: datetime) -> dict:
    """{"rain_prob": 0-100, "temp_c": float, "source": "open-meteo" | "stub"} for the hour of `when` (local time)."""
    key = (round(lat, 2), round(lng, 2), when.strftime("%Y-%m-%dT%H"))
    if key in _cache:
        return _cache[key]
    if os.getenv("WEATHER_STUB"):
        return dict(STUB)
    try:
        q = urllib.parse.urlencode({
            "latitude": key[0], "longitude": key[1],
            "hourly": "precipitation_probability,temperature_2m",
            "timezone": os.getenv("TZ", "America/Los_Angeles"),
            "start_date": when.date().isoformat(), "end_date": when.date().isoformat(),
        })
        with urllib.request.urlopen(f"https://api.open-meteo.com/v1/forecast?{q}", timeout=TIMEOUT_S) as r:
            data = json.load(r)["hourly"]
        i = data["time"].index(key[2] + ":00")
        out = {"rain_prob": int(data["precipitation_probability"][i] or 0),
               "temp_c": float(data["temperature_2m"][i]), "source": "open-meteo"}
    except Exception:
        out = dict(STUB)
    _cache[key] = out
    return out
