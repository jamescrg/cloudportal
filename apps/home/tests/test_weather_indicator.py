"""The home page's weather indicator and the saved location. The API is
always mocked."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests
from django.core.cache import cache
from django.urls import reverse

from apps.home.views import fetch_current_weather

pytestmark = pytest.mark.django_db

GET = "apps.weather.service.requests.get"
ONECALL = Path(__file__).parents[2] / "weather" / "tests" / "fixtures" / "onecall.json"


@pytest.fixture(autouse=True)
def empty_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def located(user):
    user.weather_lat, user.weather_lon = 36.85, -76.29
    user.save()
    return user


def api_response(payload):
    response = MagicMock()
    response.json.return_value = payload
    return response


def test_fetch_current_weather(located):
    onecall = json.loads(ONECALL.read_text())
    with patch(GET, return_value=api_response(onecall)):
        assert fetch_current_weather(located) == {
            "temp": 64,
            "icon": "cloudy",
            "owm_icon": "04d",
            "description": "overcast clouds",
        }


def test_fetch_current_weather_when_the_api_fails(located):
    with patch(GET, side_effect=requests.ConnectionError):
        assert fetch_current_weather(located) is None


def test_fetch_current_weather_without_a_location(user):
    with patch(GET) as get:
        assert fetch_current_weather(user) is None
    get.assert_not_called()


def test_save_location_clears_the_place(client, user):
    user.weather_lat, user.weather_lon = 36.85, -76.29
    user.weather_place = "Norfolk, Virginia"
    user.save()
    response = client.post(
        reverse("home-save-location"), {"lat": "48.85", "lon": "2.35"}
    )
    assert response.status_code == 200
    assert response.json() == {"success": True}
    user.refresh_from_db()
    assert (user.weather_lat, user.weather_lon) == (48.85, 2.35)
    assert user.weather_place == ""


def test_save_location_rejects_bad_coordinates(client, user):
    response = client.post(
        reverse("home-save-location"), {"lat": "north", "lon": "2.35"}
    )
    assert response.json()["success"] is False
    user.refresh_from_db()
    assert user.weather_lat is None
