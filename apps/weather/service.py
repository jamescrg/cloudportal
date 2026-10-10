"""The weather report: one call to OpenWeather's One Call API, cached, and
reshaped into what the page and the home page's indicator show.

Every time in the report is the location's own local time, from the
offset the API returns with the data, so the page is right wherever the
browser placed the user. Amounts come back in millimetres whatever the
units, and are shown in inches."""

from datetime import datetime, timedelta, timezone

import requests
from django.conf import settings
from django.core.cache import cache

ONE_CALL_URL = "https://api.openweathermap.org/data/3.0/onecall"
REVERSE_GEOCODE_URL = "https://api.openweathermap.org/geo/1.0/reverse"
TIMEOUT = 5
# One Call is billed per call past the free thousand a day; the home
# page's indicator and the weather page share one report for ten minutes
CACHE_SECONDS = 600
HOURS_SHOWN = 24

# OpenWeather's icon codes (less their d/n suffix) as Lucide icons, by day
# and by night
ICONS = {
    "01": ("sun", "moon"),
    "02": ("cloud-sun", "cloud-moon"),
    "03": ("cloud", "cloud"),
    "04": ("cloudy", "cloudy"),
    "09": ("cloud-drizzle", "cloud-drizzle"),
    "10": ("cloud-sun-rain", "cloud-moon-rain"),
    "11": ("cloud-lightning", "cloud-lightning"),
    "13": ("cloud-snow", "cloud-snow"),
    "50": ("cloud-fog", "cloud-fog"),
}

COMPASS = [
    "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
    "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
]  # fmt: skip


def icon_for(code):
    """The Lucide icon for an OpenWeather icon code such as 10n."""
    day, night = ICONS.get(code[:2], ("cloud", "cloud"))
    return night if code.endswith("n") else day


def compass(degrees):
    """A sixteen-point compass direction for a bearing in degrees."""
    if degrees is None:
        return ""
    return COMPASS[int((degrees + 11.25) // 22.5) % 16]


def uv_level(uvi):
    if uvi < 3:
        return "low"
    if uvi < 6:
        return "moderate"
    if uvi < 8:
        return "high"
    if uvi < 11:
        return "very high"
    return "extreme"


def moon_phase_name(phase):
    """OpenWeather gives the phase as 0..1, new moon to new moon."""
    names = [
        "new moon", "waxing crescent", "first quarter", "waxing gibbous",
        "full moon", "waning gibbous", "last quarter", "waning crescent",
    ]  # fmt: skip
    return names[int((phase + 0.0625) * 8) % 8]


def inches(millimetres):
    """Millimetres as inches to a tenth; a trace is shown as a trace."""
    if not millimetres:
        return ""
    value = millimetres / 25.4
    return "<0.1" if value < 0.05 else f"{value:.1f}"


def clock(dt):
    """A time like 7:38 AM."""
    return dt.strftime("%I:%M %p").lstrip("0")


def hour_label(dt):
    """An hour like 2 PM."""
    return dt.strftime("%I %p").lstrip("0")


def cache_key(lat, lon):
    # three decimals is about a hundred metres: the same forecast
    return f"weather:onecall:{lat:.3f},{lon:.3f}"


def fetch_one_call(lat, lon):
    """The One Call response for a location, from the cache when it is
    fresh; None when OpenWeather can't be reached or answers with an
    error."""
    key = cache_key(lat, lon)
    data = cache.get(key)
    if data is not None:
        return data
    params = {
        "lat": lat,
        "lon": lon,
        "units": "imperial",
        "appid": settings.OPEN_WEATHER_API_KEY,
    }
    try:
        response = requests.get(ONE_CALL_URL, params=params, timeout=TIMEOUT)
        data = response.json()
    except (requests.RequestException, ValueError):
        return None
    if not isinstance(data, dict) or "current" not in data or "daily" not in data:
        return None
    cache.set(key, data, CACHE_SECONDS)
    return data


def reverse_geocode(lat, lon):
    """The place at a location as 'Town, State' (or 'Town, Country' outside
    the US); '' when it can't be found."""
    params = {
        "lat": lat,
        "lon": lon,
        "limit": 1,
        "appid": settings.OPEN_WEATHER_API_KEY,
    }
    try:
        response = requests.get(REVERSE_GEOCODE_URL, params=params, timeout=TIMEOUT)
        places = response.json()
    except (requests.RequestException, ValueError):
        return ""
    if not isinstance(places, list) or not places:
        return ""
    place = places[0]
    name = place.get("name", "")
    region = (
        place.get("state") if place.get("country") == "US" else place.get("country")
    )
    return f"{name}, {region}" if name and region else name


def place_name(user):
    """The user's place, looked up once per saved location and kept on the
    user."""
    if user.weather_place:
        return user.weather_place
    name = reverse_geocode(user.weather_lat, user.weather_lon)
    if name:
        user.weather_place = name
        user.save(update_fields=["weather_place"])
    return name


def precipitation_kind(weather):
    main = weather[0]["main"] if weather else ""
    if main == "Snow":
        return "snow"
    if main in ("Rain", "Drizzle", "Thunderstorm"):
        return "rain"
    return "precipitation"


def next_hour(minutely, kind):
    """What the next sixty minutes hold, from the minute-by-minute
    precipitation: None when the API didn't send it."""
    if not minutely:
        return None
    amounts = [minute.get("precipitation", 0) for minute in minutely]
    wet = [amount > 0 for amount in amounts]
    if not any(wet):
        return {"text": f"No {kind} expected in the next hour", "wet": False}
    if wet[0]:
        if all(wet):
            return {"text": f"{kind.capitalize()} for the next hour", "wet": True}
        ends = wet.index(False)
        later = any(wet[ends:])
        text = f"{kind.capitalize()} for the next {ends} minutes"
        if later:
            text += ", then more later in the hour"
        return {"text": text, "wet": True}
    starts = wet.index(True)
    return {"text": f"{kind.capitalize()} starting in {starts} minutes", "wet": True}


def wind(entry):
    """Wind as the page shows it: speed, direction and gust when the gust
    is worth mentioning."""
    speed = round(entry.get("wind_speed", 0))
    gust = entry.get("wind_gust")
    gust = round(gust) if gust and round(gust) > speed else None
    direction = compass(entry.get("wind_deg"))
    text = f"{speed} mph {direction}".rstrip()
    if gust:
        text += f", gusts {gust}"
    return {
        "wind_speed": speed,
        "wind_dir": direction,
        "wind_gust": gust,
        "wind_text": text,
    }


def alert_key(alert):
    """What identifies an alert from one response to the next."""
    return f"{alert.get('event', '')}|{alert.get('start', '')}|{alert.get('end', '')}"


def dismiss_alert(user, key):
    """Clear an alert from the user's page until it ends, and forget the
    alerts already over."""
    now = datetime.now(timezone.utc).timestamp()
    keys = [k for k in user.weather_dismissed_alerts if k != key]
    keys.append(key)
    kept = []
    for k in keys:
        end = k.rsplit("|", 1)[-1]
        if end.isdigit() and int(end) < now:
            continue
        kept.append(k)
    user.weather_dismissed_alerts = kept
    user.save(update_fields=["weather_dismissed_alerts"])


def build_report(data, dismissed=()):
    """The page's report from a One Call response, less the alerts the
    user has cleared."""
    tz = timezone(timedelta(seconds=data.get("timezone_offset", 0)))

    def local(ts):
        return datetime.fromtimestamp(ts, tz)

    now = data["current"]
    today = data["daily"][0]
    now_dt = local(now["dt"])
    today_date = now_dt.date()

    current = {
        "updated": clock(now_dt),
        "description": now["weather"][0]["description"],
        "icon": icon_for(now["weather"][0]["icon"]),
        "owm_icon": now["weather"][0]["icon"],
        "temp": round(now["temp"]),
        "feels_like": round(now["feels_like"]),
        "high": round(today["temp"]["max"]),
        "low": round(today["temp"]["min"]),
        "humidity": now.get("humidity"),
        "dew_point": round(now["dew_point"]) if "dew_point" in now else None,
        "pressure": now.get("pressure"),
        "clouds": now.get("clouds"),
        "visibility_miles": (
            round(now["visibility"] / 1609.34, 1)
            if now.get("visibility") is not None
            else None
        ),
        "uvi": round(now.get("uvi", 0)),
        "uv_level": uv_level(now.get("uvi", 0)),
        "pop": round(today.get("pop", 0) * 100),
        # what is falling right now, in inches an hour
        "rain_rate": inches(now.get("rain", {}).get("1h")),
        "snow_rate": inches(now.get("snow", {}).get("1h")),
        "rain_today": inches(today.get("rain")),
        "snow_today": inches(today.get("snow")),
        "summary": today.get("summary", ""),
        "sunrise": clock(local(now["sunrise"])) if "sunrise" in now else "",
        "sunset": clock(local(now["sunset"])) if "sunset" in now else "",
        **wind(now),
    }

    hourly = []
    for hour in data.get("hourly", [])[1:][:HOURS_SHOWN]:
        dt = local(hour["dt"])
        rain = hour.get("rain", {}).get("1h", 0) + hour.get("snow", {}).get("1h", 0)
        hourly.append(
            {
                "label": hour_label(dt),
                "day": dt.strftime("%A") if dt.date() != today_date else "",
                "new_day": dt.hour == 0,
                "temp": round(hour["temp"]),
                "feels_like": round(hour["feels_like"]),
                "pop": round(hour.get("pop", 0) * 100),
                "precip": inches(rain),
                "description": hour["weather"][0]["description"],
                "icon": icon_for(hour["weather"][0]["icon"]),
                "owm_icon": hour["weather"][0]["icon"],
                "uvi": round(hour.get("uvi", 0)),
                "humidity": hour.get("humidity"),
                **wind(hour),
            }
        )

    daily = []
    for index, day in enumerate(data["daily"]):
        dt = local(day["dt"])
        daily.append(
            {
                "name": "Today" if index == 0 else dt.strftime("%A"),
                "date": dt.strftime("%b %-d"),
                "low": round(day["temp"]["min"]),
                "high": round(day["temp"]["max"]),
                "morn": round(day["temp"]["morn"]),
                "day": round(day["temp"]["day"]),
                "eve": round(day["temp"]["eve"]),
                "night": round(day["temp"]["night"]),
                "pop": round(day.get("pop", 0) * 100),
                "precip": inches(day.get("rain", 0) + day.get("snow", 0)),
                "summary": day.get("summary", ""),
                "description": day["weather"][0]["description"],
                "icon": icon_for(day["weather"][0]["icon"]),
                "owm_icon": day["weather"][0]["icon"],
                "uvi": round(day.get("uvi", 0)),
                "uv_level": uv_level(day.get("uvi", 0)),
                "humidity": day.get("humidity"),
                "sunrise": clock(local(day["sunrise"])) if "sunrise" in day else "",
                "sunset": clock(local(day["sunset"])) if "sunset" in day else "",
                "moon_phase": moon_phase_name(day.get("moon_phase", 0)),
                **wind(day),
            }
        )

    alerts = []
    seen = set()
    for alert in sorted(data.get("alerts", []), key=lambda a: a.get("start", 0)):
        key = alert_key(alert)
        if key in seen or key in dismissed:
            continue
        seen.add(key)
        end = local(alert["end"]) if alert.get("end") else None
        until = ""
        if end:
            day = "today" if end.date() == today_date else end.strftime("%A")
            until = f"until {clock(end)} {day}"
        alerts.append(
            {
                "key": key,
                "event": alert.get("event", "Alert"),
                "sender": alert.get("sender_name", ""),
                "until": until,
                "description": alert.get("description", ""),
                "tags": alert.get("tags", []),
            }
        )

    return {
        "current": current,
        "next_hour": next_hour(
            data.get("minutely"), precipitation_kind(now["weather"])
        ),
        "hourly": hourly,
        "daily": daily,
        "alerts": alerts,
        "timezone": data.get("timezone", ""),
    }


def has_location(user):
    """Whether the user has saved coordinates (zero is a coordinate too)."""
    return user.weather_lat is not None and user.weather_lon is not None


def report_for(user):
    """The user's weather report, or None when they have no location or
    OpenWeather is unavailable."""
    if not has_location(user):
        return None
    data = fetch_one_call(user.weather_lat, user.weather_lon)
    if not data:
        return None
    return build_report(data, user.weather_dismissed_alerts or ())
