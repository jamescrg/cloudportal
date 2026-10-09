"""Events from the user's Kosmos on the calendar: the connection kept in
Settings, the feed, the toggle, and a Kosmos that does not answer."""

import pytest
import requests
from django.urls import reverse

from apps.calendar import kosmos

pytestmark = pytest.mark.django_db

MARCH = {"start": "2030-03-01", "end": "2030-03-31"}
ANSWER = {
    "time_zone": "America/Chicago",
    "events": [
        {
            "id": 7,
            "title": "Smith v. Jones - Hearing - JC",
            "date": "2030-03-04",
            "start_time": "09:00:00",
            "end_time": "10:30:00",
            "all_day": False,
            "matter": "Smith v. Jones",
            "location": "Courtroom 3",
            "url": "https://kosmos.example.com/events/7/edit",
        },
        {
            "id": 8,
            "title": "Filing deadline",
            "date": "2030-03-05",
            "start_time": None,
            "end_time": None,
            "all_day": True,
            "matter": "",
            "location": "",
            "url": "https://kosmos.example.com/events/8/edit",
        },
    ],
}


class FakeKosmos:
    """Stands in for a Kosmos: records the request and answers, or fails."""

    def __init__(self, answer=ANSWER, fail=False):
        self.answer = answer
        self.fail = fail
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append({"url": url, "params": params, "headers": headers})
        if self.fail:
            raise requests.ConnectionError("Kosmos is down")
        answer = self.answer

        class Response:
            def raise_for_status(self):
                pass

            def json(self):
                return answer

        return Response()


@pytest.fixture
def connected(user):
    user.kosmos_url = "https://kosmos.example.com"
    user.kosmos_token = "tok_123"
    user.time_zone = "America/New_York"
    user.save()
    return user


@pytest.fixture
def fake(monkeypatch):
    fake = FakeKosmos()
    monkeypatch.setattr(kosmos.requests, "get", fake.get)
    return fake


def _feed(client):
    return {row["id"]: row for row in client.get(reverse("calendar:api"), MARCH).json()}


# --- the feed ----------------------------------------------------------------


def test_kosmos_events_join_the_feed_read_only(client, connected, fake):
    rows = _feed(client)

    assert set(rows) == {"kosmos-7", "kosmos-8"}
    hearing = rows["kosmos-7"]
    assert hearing["title"] == "Smith v. Jones - Hearing - JC"
    assert hearing["className"] == "fc-event-kosmos"
    assert hearing["editable"] is False
    # Kosmos's 9:00 Central, as a moment with its offset
    assert hearing["start"] == "2030-03-04T09:00:00-06:00"
    assert hearing["end"] == "2030-03-04T10:30:00-06:00"
    assert hearing["allDay"] is False
    assert hearing["extendedProps"]["kind"] == "kosmos"
    assert hearing["extendedProps"]["url"] == "https://kosmos.example.com/events/7/edit"
    deadline = rows["kosmos-8"]
    assert (deadline["start"], deadline["allDay"]) == ("2030-03-05", True)


def test_kosmos_is_asked_for_the_range_with_the_token(client, connected, fake):
    client.get(reverse("calendar:api"), MARCH)

    call = fake.calls[0]
    assert call["url"] == "https://kosmos.example.com/events/api/"
    assert call["headers"] == {"X-Kosmos-Token": "tok_123"}
    assert (
        call["params"]["start"] <= "2030-03-01"
        and call["params"]["end"] >= "2030-03-31"
    )


def test_without_a_kosmos_nothing_is_asked(client, user, fake):
    assert _feed(client) == {}
    assert fake.calls == []


def test_a_kosmos_that_is_down_contributes_nothing(client, connected, monkeypatch):
    monkeypatch.setattr(kosmos.requests, "get", FakeKosmos(fail=True).get)

    response = client.get(reverse("calendar:api"), MARCH)

    assert response.status_code == 200 and response.json() == []


def test_a_kosmos_that_answers_badly_contributes_nothing(
    client, connected, monkeypatch
):
    monkeypatch.setattr(kosmos.requests, "get", FakeKosmos(answer={"nope": 1}).get)

    assert client.get(reverse("calendar:api"), MARCH).json() == []


# --- the toggle --------------------------------------------------------------


def test_the_toolbar_offers_the_toggle_only_with_a_kosmos(client, user, connected):
    html = client.get(reverse("calendar:index")).content.decode()
    assert reverse("calendar:show-kosmos", args=["off"]) in html

    user.kosmos_url = ""
    user.save()
    html = client.get(reverse("calendar:index")).content.decode()
    assert "show-kosmos" not in html and "kosmos/" not in html


def test_hiding_kosmos_events_takes_them_off_the_feed(client, connected, fake):
    response = client.post(reverse("calendar:show-kosmos", args=["off"]))
    assert response.status_code == 204

    assert _feed(client) == {}
    assert (
        reverse("calendar:show-kosmos", args=["on"])
        in client.get(reverse("calendar:index")).content.decode()
    )

    client.post(reverse("calendar:show-kosmos", args=["on"]))
    assert set(_feed(client)) == {"kosmos-7", "kosmos-8"}


# --- settings ------------------------------------------------------------------


def test_saving_the_connection(client, user):
    response = client.post(
        reverse("settings-calendar-kosmos"),
        {"kosmos_url": "https://kosmos.example.com/", "kosmos_token": "tok_123"},
    )

    assert response.status_code == 302
    user.refresh_from_db()
    assert (user.kosmos_url, user.kosmos_token) == (
        "https://kosmos.example.com",
        "tok_123",
    )


def test_the_address_must_be_one(client, user):
    response = client.post(
        reverse("settings-calendar-kosmos"),
        {"kosmos_url": "kosmos", "kosmos_token": "t"},
    )

    assert "Enter the address" in response.content.decode()
    user.refresh_from_db()
    assert user.kosmos_url == ""


def test_testing_the_connection_reports_the_count(client, user, fake):
    client.post(
        reverse("settings-calendar-kosmos"),
        {
            "kosmos_url": "https://kosmos.example.com",
            "kosmos_token": "t",
            "action": "test",
        },
    )

    page = client.get(reverse("settings-calendar")).content.decode()
    assert "Kosmos has 2 event(s) for you this month" in page


def test_testing_a_kosmos_that_is_down_reports_it(client, user, monkeypatch):
    monkeypatch.setattr(kosmos.requests, "get", FakeKosmos(fail=True).get)

    client.post(
        reverse("settings-calendar-kosmos"),
        {
            "kosmos_url": "https://kosmos.example.com",
            "kosmos_token": "t",
            "action": "test",
        },
    )

    assert (
        "could not be reached"
        in client.get(reverse("settings-calendar")).content.decode()
    )


def test_disconnecting_forgets_the_kosmos(client, connected):
    client.post(reverse("settings-calendar-kosmos"), {"action": "clear"})

    connected.refresh_from_db()
    assert (connected.kosmos_url, connected.kosmos_token) == ("", "")
