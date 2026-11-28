"""The weather, for the CloudPortal Weather Android app: the same report
the weather page shows (apps.weather.service), as JSON, and the page's
three changes: where the user is, their units, and an alert cleared. Each
request carries an OAuth access token (apps.api.auth); no cookies, no
CSRF."""

import json
import math

from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt

from apps.api import auth
from apps.weather.service import (
    UNITS,
    dismiss_alert,
    has_location,
    place_name,
    report_for,
    units_for,
)

MAX_BODY = 4096


def _answer(data, status=200):
    response = JsonResponse(data, status=status)
    response["Cache-Control"] = "no-store"
    return response


def _bad_request(message):
    return _answer({"error": message}, status=400)


def _not_allowed(method):
    response = HttpResponse(status=405)
    response["Allow"] = method
    return response


def _weather(user):
    """What the weather page shows this user. Without a location there is
    no report; with one and no report, OpenWeather can't be reached."""
    located = has_location(user)
    report = report_for(user) if located else None
    return {
        "has_location": located,
        "lat": user.weather_lat if located else None,
        "lon": user.weather_lon if located else None,
        "place": place_name(user) if report else "",
        "units": units_for(user.weather_units),
        "report": report,
    }


def _posted(request):
    """The user and the JSON object a POST carries, or the answer that
    refuses it."""
    if request.method != "POST":
        return None, None, _not_allowed("POST")
    access = auth.token_for(request, weather=True)
    if access is None:
        return None, None, auth.challenge(request)
    try:
        length = int(request.META.get("CONTENT_LENGTH") or 0)
    except ValueError:
        length = 0
    if length > MAX_BODY:
        return None, None, _bad_request("The request is too large.")
    try:
        message = json.loads(request.body)
    except (ValueError, UnicodeDecodeError):
        return None, None, _bad_request("The body must be JSON.")
    if not isinstance(message, dict):
        return None, None, _bad_request("The body must be a JSON object.")
    return access.user, message, None


@csrf_exempt
def weather(request):
    if request.method != "GET":
        return _not_allowed("GET")
    access = auth.token_for(request, weather=True)
    if access is None:
        return auth.challenge(request)
    return _answer(_weather(access.user))


def _coordinate(value, limit):
    # a bool is an int to Python, and not a coordinate
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or abs(value) > limit:
        return None
    return float(value)


@csrf_exempt
def location(request):
    """Where the phone is, as the page's Use my current location saves
    it; answers with the weather there."""
    user, message, refusal = _posted(request)
    if refusal:
        return refusal
    lat = _coordinate(message.get("lat"), 90)
    lon = _coordinate(message.get("lon"), 180)
    if lat is None or lon is None:
        return _bad_request("lat and lon must be a latitude and a longitude.")
    user.weather_lat = lat
    user.weather_lon = lon
    # the place is looked up again for the new location when it is next shown
    user.weather_place = ""
    user.save(update_fields=["weather_lat", "weather_lon", "weather_place"])
    return _answer(_weather(user))


@csrf_exempt
def units(request):
    """Imperial or metric from now on, on the site too; answers with the
    weather in them."""
    user, message, refusal = _posted(request)
    if refusal:
        return refusal
    choice = message.get("units")
    if not isinstance(choice, str) or choice not in UNITS:
        return _bad_request('units must be "imperial" or "metric".')
    user.weather_units = choice
    user.save(update_fields=["weather_units"])
    return _answer(_weather(user))


@csrf_exempt
def dismiss(request):
    """Clear an alert until it ends, on the site too."""
    user, message, refusal = _posted(request)
    if refusal:
        return refusal
    key = message.get("key")
    if not isinstance(key, str) or not key.strip() or len(key) > 300:
        return _bad_request("key must be an alert's key.")
    dismiss_alert(user, key.strip())
    return _answer({"ok": True})
