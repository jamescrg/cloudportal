from datetime import datetime

import requests
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from apps.weather.timeshift import timestamp_to_eastern


@login_required
def index(request):
    """Display current weather conditions using stored lat/lon coordinates."""

    user = request.user
    has_location = user.weather_lat and user.weather_lon

    if not has_location:
        context = {
            "page": "weather",
            "current": None,
            "forecast": None,
        }
        return render(request, "weather/content.html", context)

    # fetch current weather data
    url = "https://api.openweathermap.org/data/2.5/weather"
    params = {
        "lat": user.weather_lat,
        "lon": user.weather_lon,
        "units": "imperial",
        "appid": settings.OPEN_WEATHER_API_KEY,
    }
    response = requests.get(url, params=params)
    current = response.json()

    if "message" in current:
        context = {
            "page": "weather",
            "current": None,
            "forecast": None,
        }
        return render(request, "weather/content.html", context)

    # convert sunrise/sunset to Eastern time
    sunrise = timestamp_to_eastern(current["sys"]["sunrise"])
    current["sunrise"] = sunrise.strftime("%I:%M %p")
    sunset = timestamp_to_eastern(current["sys"]["sunset"])
    current["sunset"] = sunset.strftime("%I:%M %p")

    # fetch forecast data
    url = "https://api.openweathermap.org/data/3.0/onecall"
    params["lon"] = current["coord"]["lon"]
    params["lat"] = current["coord"]["lat"]
    params["exclude"] = "minutely"
    response = requests.get(url, params=params)
    forecast = response.json()

    forecast["daily"] = forecast["daily"][1:]
    forecast["hourly"] = forecast["hourly"][1:13]

    for hour in forecast["hourly"]:
        hour_time = timestamp_to_eastern(hour["dt"])
        hour["hour_time"] = hour_time.strftime("%I:%M")

    for day in forecast["daily"]:
        date = datetime.fromtimestamp(day["dt"])
        day["date_string"] = date.strftime("%A")

    context = {
        "page": "weather",
        "current": current,
        "forecast": forecast,
    }
    return render(request, "weather/content.html", context)
