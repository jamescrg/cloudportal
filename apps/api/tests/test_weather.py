"""The weather app signs in as a client of its own and reads the weather
page's report as JSON; its token opens the weather alone, and the tasks
app's token opens the weather too. OpenWeather is always mocked."""

import importlib
import json
import re
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlencode, urlparse

import pytest
from django.apps import apps as django_apps
from django.conf import settings
from django.core.cache import cache
from django.test import Client
from oauth2_provider.models import Application

from apps.api.tests import conftest as tasks_app
from apps.common.notify import app_ready
from apps.weather import service

pytestmark = pytest.mark.django_db

CLIENT_ID = "cloudportal-weather-android"
REDIRECT_URI = "net.cloudportal.weather:/oauth"
GET = "apps.weather.service.requests.get"
PLACES = [{"name": "Norfolk", "state": "Virginia", "country": "US"}]
ONECALL = (
    Path(service.__file__).parent / "tests" / "fixtures" / "onecall.json"
).read_text()


def fake_api(url, params=None, timeout=None):
    response = MagicMock()
    response.json.return_value = (
        json.loads(ONECALL) if url == service.ONE_CALL_URL else PLACES
    )
    return response


@pytest.fixture(autouse=True)
def empty_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def weather_app():
    if not Application.objects.filter(client_id=CLIENT_ID).exists():
        migration = importlib.import_module(
            "apps.api.migrations.0003_weather_android_client"
        )
        migration.add_client(django_apps, None)
    return Application.objects.get(client_id=CLIENT_ID)


def sign_in(browser):
    """Authorize with PKCE, press Allow, and trade the code: the weather
    app's tokens, by the real flow."""
    verifier, challenge = tasks_app.pkce_pair()
    query = urlencode(
        {
            "response_type": "code",
            "client_id": CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
            "scope": settings.CONNECTOR_SCOPE,
            "state": "xyz",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "resource": settings.API_URL,
        }
    )
    page = browser.get("/oauth/authorize/?" + query)
    assert page.status_code == 200, page.content
    fields = dict(
        re.findall(
            r'<input type="hidden" name="(\w+)" value="([^"]*)"', page.content.decode()
        )
    )
    fields["allow"] = "Authorize"
    answer = browser.post("/oauth/authorize/?" + query, fields)
    assert answer.status_code == 302, answer.content
    back = urlparse(answer["Location"])
    assert f"{back.scheme}:{back.path}" == REDIRECT_URI
    response = Client().post(
        "/oauth/token/",
        {
            "grant_type": "authorization_code",
            "code": parse_qs(back.query)["code"][0],
            "redirect_uri": REDIRECT_URI,
            "client_id": CLIENT_ID,
            "code_verifier": verifier,
            "resource": settings.API_URL,
        },
    )
    assert response.status_code == 200, response.content
    return response.json()


@pytest.fixture
def token(browser, weather_app):
    return sign_in(browser)["access_token"]


@pytest.fixture
def located(user):
    user.weather_lat, user.weather_lon = 36.85, -76.29
    user.save()
    return user


def bearer(token):
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


def get(token):
    return Client().get("/api/v1/weather", **bearer(token))


def post(token, path, body):
    return Client().post(
        f"/api/v1/weather/{path}",
        body,
        content_type="application/json",
        **bearer(token),
    )


def test_the_migration_registers_the_app_as_a_public_client(weather_app):
    assert weather_app.name == "CloudPortal Weather for Android"
    assert weather_app.client_type == Application.CLIENT_PUBLIC
    assert weather_app.redirect_uris == REDIRECT_URI
    assert weather_app.client_secret == ""


def test_the_consent_page_says_what_the_weather_app_can_do(browser, weather_app):
    _, challenge = tasks_app.pkce_pair()
    query = tasks_app.authorize_query(challenge, client_id=CLIENT_ID).replace(
        "net.cloudportal.tasks", "net.cloudportal.weather"
    )

    page = browser.get("/oauth/authorize/?" + query).content

    assert b"Connect CloudPortal Weather for Android?" in page
    assert b"CloudPortal's own app" in page
    assert b"read your weather" in page
    assert b"your tasks" not in page


def test_the_tasks_apps_consent_page_is_as_it_was(browser, android_app):
    _, challenge = tasks_app.pkce_pair()

    page = browser.get(
        "/oauth/authorize/?" + tasks_app.authorize_query(challenge)
    ).content

    assert b"your tasks and task lists" in page
    assert b"read your weather" not in page


def test_no_token_is_asked_to_sign_in():
    answers = [Client().get("/api/v1/weather")] + [
        Client().post(f"/api/v1/weather/{path}", {}, content_type="application/json")
        for path in ("location", "units", "alerts/dismiss")
    ]
    for response in answers:
        assert response.status_code == 401
        assert response["WWW-Authenticate"].startswith("Bearer ")


def test_the_wrong_method_is_refused(token):
    assert Client().post("/api/v1/weather", **bearer(token)).status_code == 405
    assert Client().get("/api/v1/weather/units", **bearer(token)).status_code == 405


def test_without_a_location_there_is_no_report(token):
    with patch(GET) as api:
        data = get(token).json()

    assert data["has_location"] is False
    assert data["report"] is None
    assert data["lat"] is None
    api.assert_not_called()


def test_the_report_is_the_pages(token, located):
    with patch(GET, side_effect=fake_api):
        response = get(token)
        data = response.json()
        page = service.report_for(located)

    assert response["Cache-Control"] == "no-store"
    assert data["has_location"] is True
    assert (data["lat"], data["lon"]) == (36.85, -76.29)
    assert data["place"] == "Norfolk, Virginia"
    assert data["units"] == "imperial"
    assert data["report"] == json.loads(json.dumps(page))
    assert len(data["report"]["hourly"]) == 24
    assert data["report"]["daily"][0]["name"] == "Today"


def test_openweather_out_of_reach_is_a_location_without_a_report(token, located):
    with patch(GET, side_effect=service.requests.ConnectionError):
        data = get(token).json()

    assert data["has_location"] is True
    assert data["report"] is None
    assert data["place"] == ""


def test_the_location_is_saved_and_the_place_looked_up_again(token, located):
    located.weather_place = "Paris, Ile-de-France"
    located.save()

    with patch(GET, side_effect=fake_api):
        data = post(token, "location", {"lat": 36.9, "lon": -76.2}).json()

    located.refresh_from_db()
    assert (located.weather_lat, located.weather_lon) == (36.9, -76.2)
    assert data["place"] == "Norfolk, Virginia"
    assert data["report"]["current"]


@pytest.mark.parametrize(
    "body",
    [
        {"lat": "north", "lon": 2.35},
        {"lat": 91, "lon": 2.35},
        {"lat": 48.85, "lon": 181},
        {"lat": True, "lon": 2.35},
        {"lat": 48.85},
        [48.85, 2.35],
    ],
)
def test_a_bad_location_is_refused(token, located, body):
    response = post(token, "location", body)

    located.refresh_from_db()
    assert response.status_code == 400
    assert response.json()["error"]
    assert (located.weather_lat, located.weather_lon) == (36.85, -76.29)


def test_the_units_are_saved_and_the_report_is_in_them(token, located):
    with patch(GET, side_effect=fake_api):
        imperial = get(token).json()
        metric = post(token, "units", {"units": "metric"}).json()

    located.refresh_from_db()
    assert located.weather_units == "metric"
    assert metric["units"] == "metric"
    assert metric["report"]["units"]["temp"] == "°C"
    assert metric["report"]["current"]["temp"] < imperial["report"]["current"]["temp"]


def test_unknown_units_are_refused(token, located):
    response = post(token, "units", {"units": "kelvin"})

    located.refresh_from_db()
    assert response.status_code == 400
    assert located.weather_units == "imperial"


def far_off_alert(url, params=None, timeout=None):
    """The fixture's alerts ended in October 2026, and a cleared alert is
    forgotten once it is over: one that is not, for the clearing."""
    response = fake_api(url, params, timeout)
    if url == service.ONE_CALL_URL:
        data = response.json.return_value
        data["alerts"][0]["end"] = 9999999999
    return response


def test_a_cleared_alert_leaves_the_report(token, located):
    with patch(GET, side_effect=far_off_alert):
        alerts = get(token).json()["report"]["alerts"]
        key = next(a["key"] for a in alerts if a["key"].endswith("|9999999999"))
        answer = post(token, "alerts/dismiss", {"key": key})
        left = get(token).json()["report"]["alerts"]

    located.refresh_from_db()
    assert answer.json() == {"ok": True}
    assert located.weather_dismissed_alerts == [key]
    assert key not in [alert["key"] for alert in left]
    assert len(left) == len(alerts) - 1


def test_an_alert_needs_its_key(token, located):
    assert post(token, "alerts/dismiss", {"key": " "}).status_code == 400
    assert post(token, "alerts/dismiss", {}).status_code == 400


def test_the_weather_apps_token_does_not_open_the_tasks(token):
    sync = Client().get("/api/v1/sync", **bearer(token))
    ops = Client().post(
        "/api/v1/ops", {"ops": []}, content_type="application/json", **bearer(token)
    )

    assert sync.status_code == 401
    assert ops.status_code == 401


def test_the_weather_apps_token_does_not_open_the_connector(token):
    response = Client().post(
        "/mcp", {}, content_type="application/json", **bearer(token)
    )

    assert response.status_code == 401


def test_the_tasks_apps_token_opens_the_weather(tokens, located):
    with patch(GET, side_effect=fake_api):
        response = get(tokens["access_token"])

    assert response.status_code == 200
    assert response.json()["report"]


def test_the_weather_app_is_not_the_phone_app_for_reminders(token, user):
    assert app_ready(user) is False


def test_both_apps_are_the_sites_own():
    assert settings.ANDROID_APPS == {
        "cloudportal-android": "net.cloudportal.tasks:/oauth",
        CLIENT_ID: REDIRECT_URI,
    }
