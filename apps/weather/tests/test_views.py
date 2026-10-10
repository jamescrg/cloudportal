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


def test_dismiss_clears_an_alert_for_the_user(client, user):
    from django.urls import reverse

    response = client.post(
        reverse("weather-dismiss-alert"), {"key": "Flood Watch|1|9999999999"}
    )
    assert response.status_code == 200
    assert response.json() == {"success": True}
    user.refresh_from_db()
    assert user.weather_dismissed_alerts == ["Flood Watch|1|9999999999"]


def test_dismiss_needs_a_key_and_a_post(client):
    from django.urls import reverse

    assert client.post(reverse("weather-dismiss-alert"), {}).status_code == 400
    assert client.get(reverse("weather-dismiss-alert")).status_code == 405


def test_units_switch_is_saved_on_the_user(client, user):
    from django.urls import reverse

    response = client.post(reverse("weather-units"), {"units": "metric"})
    assert response.status_code == 200
    user.refresh_from_db()
    assert user.weather_units == "metric"
    assert (
        client.post(reverse("weather-units"), {"units": "furlongs"}).status_code == 400
    )
    user.refresh_from_db()
    assert user.weather_units == "metric"
