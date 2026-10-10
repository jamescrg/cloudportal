"""The weather report: one call to OpenWeather's One Call API, cached, and
reshaped into what the page and the home page's indicator show.

Every time in the report is the location's own local time, from the
offset the API returns with the data, so the page is right wherever the
browser placed the user. The API is always asked for imperial units, so
one cached response serves every user at a location; a user who reads
metric has the report converted."""

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


# sea-level pressure in hectopascals: the standard atmosphere, and the
# bands either side of it
AVERAGE_PRESSURE = 1013
PRESSURE_BANDS = [
    (990, "very-low", "Very low", "stormy, unsettled weather"),
    (1005, "low", "Low", "unsettled weather, often cloud and rain"),
    (1022, "average", "Near average", "typical conditions"),
    (1035, "high", "High", "settled, fair weather"),
    (None, "very-high", "Very high", "very settled, clear and calm"),
]


def pressure(hpa, units="imperial"):
    """Pressure as the page shows it: inches of mercury for an imperial
    reader, and where it sits against the average, with a tone for its
    colour."""
    if hpa is None:
        return {}
    for limit, tone, level, note in PRESSURE_BANDS:
        if limit is None or hpa < limit:
            break
    away = hpa - AVERAGE_PRESSURE
    if away > 0:
        relative = f"{away} above the {AVERAGE_PRESSURE} average"
    elif away < 0:
        relative = f"{-away} below the {AVERAGE_PRESSURE} average"
    else:
        relative = f"the {AVERAGE_PRESSURE} average"
    return {
        "pressure": hpa,
        "pressure_inhg": f"{hpa * 0.02953:.2f}" if units == "imperial" else "",
        "pressure_tone": tone,
        "pressure_level": level,
        "pressure_note": note,
        "pressure_from_average": away,
        "pressure_relative": relative,
    }


def moon_phase_name(phase):
    """OpenWeather gives the phase as 0..1, new moon to new moon."""
    names = [
        "new moon", "waxing crescent", "first quarter", "waxing gibbous",
        "full moon", "waning gibbous", "last quarter", "waning crescent",
    ]  # fmt: skip
    return names[int((phase + 0.0625) * 8) % 8]


UNITS = {
    "imperial": {"temp": "°F", "speed": "mph", "precip": "in", "distance": "mi"},
    "metric": {"temp": "°C", "speed": "km/h", "precip": "mm", "distance": "km"},
}


def units_for(name):
    return name if name in UNITS else "imperial"


def degrees(fahrenheit, units):
    """A temperature from the API's Fahrenheit, rounded, in the user's
    units."""
    if units == "metric":
        return round((fahrenheit - 32) * 5 / 9)
    return round(fahrenheit)


def speed(mph, units):
    """A wind speed from the API's miles an hour, rounded, in the user's
    units."""
    if units == "metric":
        return round(mph * 1.609344)
    return round(mph)


def distance(metres, units):
    """A visibility from the API's metres, to a tenth, in the user's
    units."""
    if units == "metric":
        return round(metres / 1000, 1)
    return round(metres / 1609.34, 1)


def amount(millimetres, units="imperial"):
    """A precipitation amount from the API's millimetres, to a tenth, in
    the user's units; a trace is shown as a trace, nothing as nothing."""
    if not millimetres:
        return ""
    value = millimetres / 25.4 if units == "imperial" else millimetres
    return "<0.1" if value < 0.05 else f"{value:.1f}"


def inches(millimetres):
    """Millimetres as inches to a tenth; a trace is shown as a trace."""
    return amount(millimetres, "imperial")


def clock(dt):
    """A time like 7:38 AM."""
    return dt.strftime("%I:%M %p").lstrip("0")


def short_clock(dt):
    """A time like 7:38 AM, or 8 AM on the hour."""
    if dt.minute == 0:
        return hour_label(dt)
    return clock(dt)


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
    # the region is a state, province, land or département; the API gives
    # the country only as a code, so a place without a region stands alone
    region = place.get("state", "")
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


def wind(entry, units="imperial"):
    """Wind as the page shows it: speed, direction and gust when the gust
    is worth mentioning."""
    wind_speed = speed(entry.get("wind_speed", 0), units)
    gust = entry.get("wind_gust")
    gust = speed(gust, units) if gust else None
    if gust is not None and gust <= wind_speed:
        gust = None
    direction = compass(entry.get("wind_deg"))
    text = f"{wind_speed} {UNITS[units]['speed']} {direction}".rstrip()
    if gust:
        text += f", gusts {gust}"
    return {
        "wind_speed": wind_speed,
        "wind_dir": direction,
        "wind_gust": gust,
        "wind_text": text,
    }


def reflow(text):
    """NWS prose comes hard-wrapped at sixty characters: join the lines of
    each paragraph, keeping a break before a list item or a heading."""
    paragraphs = []
    for paragraph in text.replace("\r", "").split("\n\n"):
        lines = []
        for line in paragraph.split("\n"):
            line = line.strip()
            if not line:
                continue
            starts_item = line.startswith(("* ", "- ", "**")) or line.endswith("-" * 3)
            if lines and not starts_item and not lines[-1].endswith("-" * 3):
                lines[-1] += " " + line
            else:
                lines.append(line)
        if lines:
            paragraphs.append("\n".join(lines))
    return "\n\n".join(paragraphs)


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


def build_report(data, dismissed=(), units="imperial"):
    """The page's report from a One Call response, in the user's units,
    less the alerts the user has cleared."""
    units = units_for(units)
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
        "temp": degrees(now["temp"], units),
        "feels_like": degrees(now["feels_like"], units),
        "high": degrees(today["temp"]["max"], units),
        "low": degrees(today["temp"]["min"], units),
        "humidity": now.get("humidity"),
        "dew_point": degrees(now["dew_point"], units) if "dew_point" in now else None,
        "clouds": now.get("clouds"),
        "visibility": (
            distance(now["visibility"], units)
            if now.get("visibility") is not None
            else None
        ),
        "uvi": round(now.get("uvi", 0)),
        "uv_level": uv_level(now.get("uvi", 0)),
        "pop": round(today.get("pop", 0) * 100),
        # what is falling right now, an hour's worth
        "rain_rate": amount(now.get("rain", {}).get("1h"), units),
        "snow_rate": amount(now.get("snow", {}).get("1h"), units),
        "rain_today": amount(today.get("rain"), units),
        "snow_today": amount(today.get("snow"), units),
        "summary": today.get("summary", ""),
        "sunrise": clock(local(now["sunrise"])) if "sunrise" in now else "",
        "sunset": clock(local(now["sunset"])) if "sunset" in now else "",
        **pressure(now.get("pressure"), units),
        **wind(now, units),
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
                "temp": degrees(hour["temp"], units),
                "feels_like": degrees(hour["feels_like"], units),
                "pop": round(hour.get("pop", 0) * 100),
                "precip": amount(rain, units),
                "description": hour["weather"][0]["description"],
                "icon": icon_for(hour["weather"][0]["icon"]),
                "owm_icon": hour["weather"][0]["icon"],
                "uvi": round(hour.get("uvi", 0)),
                "humidity": hour.get("humidity"),
                **wind(hour, units),
            }
        )

    daily = []
    for index, day in enumerate(data["daily"]):
        dt = local(day["dt"])
        daily.append(
            {
                "name": "Today" if index == 0 else dt.strftime("%A"),
                "date": dt.strftime("%b %-d"),
                "low": degrees(day["temp"]["min"], units),
                "high": degrees(day["temp"]["max"], units),
                "morn": degrees(day["temp"]["morn"], units),
                "day": degrees(day["temp"]["day"], units),
                "eve": degrees(day["temp"]["eve"], units),
                "night": degrees(day["temp"]["night"], units),
                "pop": round(day.get("pop", 0) * 100),
                "precip": amount(day.get("rain", 0) + day.get("snow", 0), units),
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
                **wind(day, units),
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
            until = f"until {short_clock(end)} {day}"
        alerts.append(
            {
                "key": key,
                "event": alert.get("event", "Alert"),
                "sender": alert.get("sender_name", ""),
                "until": until,
                "description": reflow(alert.get("description", "")),
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
        "units": UNITS[units],
        "units_name": units,
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
    return build_report(data, user.weather_dismissed_alerts or (), user.weather_units)
