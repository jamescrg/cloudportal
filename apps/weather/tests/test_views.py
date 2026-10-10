"""The weather page. The templates are being rewritten, so these assert
on the status and context, not the HTML. The API is always mocked."""

from unittest.mock import MagicMock, patch

import pytest
import requests
from django.test import Client
from django.urls import reverse
from pytest_django.asserts import assertTemplateUsed

from apps.weather import service

pytestmark = pytest.mark.django_db

GET = "apps.weather.service.requests.get"
PLACES = [{"name": "Norfolk", "state": "Virginia", "country": "US"}]


def fake_api(onecall):
    def get(url, params=None, timeout=None):
        response = MagicMock()
        response.json.return_value = onecall if url == service.ONE_CALL_URL else PLACES
        return response

    return get


@pytest.fixture
def located(user):
    user.weather_lat, user.weather_lon = 36.85, -76.29
    user.save()
    return user


def test_url():
    assert reverse("weather") == "/weather/"


def test_anonymous_is_sent_to_log_in():
    response = Client().get(reverse("weather"))
    assert response.status_code == 302
    assert "login" in response.url


def test_without_a_location(client):
    with patch(GET) as get:
        response = client.get(reverse("weather"))
    assert response.status_code == 200
    assertTemplateUsed(response, "weather/content.html")
    assert response.context["page"] == "weather"
    assert response.context["has_location"] is False
    assert response.context["report"] is None
    assert response.context["place"] == ""
    get.assert_not_called()


def test_with_a_location(client, located, onecall):
    with patch(GET, side_effect=fake_api(onecall)):
        response = client.get(reverse("weather"))
    assert response.status_code == 200
    assertTemplateUsed(response, "weather/content.html")
    assert response.context["has_location"] is True
    report = response.context["report"]
    assert report["current"]["sunrise"] == "7:38 AM"
    assert len(report["hourly"]) == 24
    assert response.context["place"] == "Norfolk, Virginia"
    located.refresh_from_db()
    assert located.weather_place == "Norfolk, Virginia"


def test_with_a_saved_place(client, located, onecall):
    located.weather_place = "Ghent, Virginia"
    located.save()
    with patch(GET, side_effect=fake_api(onecall)) as get:
        response = client.get(reverse("weather"))
    assert response.context["place"] == "Ghent, Virginia"
    # only One Call, no geocoding
    assert [c.args[0] for c in get.call_args_list] == [service.ONE_CALL_URL]


def test_when_the_api_fails(client, located):
    with patch(GET, side_effect=requests.ConnectionError):
        response = client.get(reverse("weather"))
    assert response.status_code == 200
    assert response.context["has_location"] is True
    assert response.context["report"] is None
    assert response.context["place"] == ""
