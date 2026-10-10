"""The calendar can show US federal holidays beside its events."""

from datetime import date

import pytest
from django.urls import reverse

from apps.calendar import holidays

pytestmark = pytest.mark.django_db

JULY = {"start": "2027-06-27", "end": "2027-08-07"}


def _feed(client, params):
    return {
        row["id"]: row for row in client.get(reverse("calendar:api"), params).json()
    }


def test_holidays_are_off_by_default(client):
    assert not any(key.startswith("holiday-") for key in _feed(client, JULY))
    assert client.get("/calendar/").context["show_holidays"] is False


def test_the_toggle(client):
    response = client.post(reverse("calendar:show-holidays", args=["on"]))

    assert response.status_code == 204
    assert response["HX-Trigger"] == "eventsViewChanged"
    assert client.get("/calendar/").context["show_holidays"] is True
    assert "Hide holidays" in client.get("/calendar/").content.decode()

    client.post(reverse("calendar:show-holidays", args=["off"]))
    assert client.get("/calendar/").context["show_holidays"] is False
    assert (
        client.post(reverse("calendar:show-holidays", args=["maybe"])).status_code
        == 400
    )


def test_the_holidays_in_the_range_show(client):
    client.post(reverse("calendar:show-holidays", args=["on"]))

    feed = _feed(client, JULY)
    shown = {key for key in feed if key.startswith("holiday-")}

    # Independence Day 2027 is a Sunday, so the Monday is observed too
    assert shown == {"holiday-2027-07-04", "holiday-2027-07-05"}
    fourth = feed["holiday-2027-07-04"]
    assert fourth["title"] == "Independence Day"
    assert fourth["allDay"] is True
    assert fourth["start"] == "2027-07-04"
    assert fourth["className"] == "fc-event-holiday"
    assert fourth["editable"] is False
    assert fourth["extendedProps"] == {"kind": "holiday"}
    assert feed["holiday-2027-07-05"]["title"] == "Independence Day (observed)"


def test_a_range_over_the_new_year_has_both_years():
    days = [row["start"] for row in holidays.feed(date(2026, 12, 20), date(2027, 1, 5))]

    assert days == ["2026-12-25", "2027-01-01"]


def test_the_header_offers_the_toggle(client):
    html = client.get("/calendar/").content.decode()

    assert reverse("calendar:show-holidays", args=["on"]) in html
    assert "Show holidays" in html
