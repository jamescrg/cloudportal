"""An event over several days: it has an end date, shows on every day it
covers, and goes to and from Google with its whole span."""

import json
from datetime import date, time, timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

import apps.calendar.google as google
import apps.calendar.sync as sync
from apps.calendar.forms import EventForm
from apps.calendar.models import Event

pytestmark = pytest.mark.django_db

MARCH = {"start": "2030-03-01", "end": "2030-04-01"}


def _data(**changes):
    return {"date": "2030-03-04", "description": "Conference"} | changes


def _feed(client, params=MARCH):
    return {
        row["id"]: row for row in client.get(reverse("calendar:api"), params).json()
    }


# --- the form --------------------------------------------------------------


def test_an_end_date_after_the_date_is_kept():
    form = EventForm(_data(end_date="2030-03-06"))

    assert form.is_valid()
    assert form.cleaned_data["end_date"] == date(2030, 3, 6)


def test_an_end_date_equal_to_the_date_is_none():
    form = EventForm(_data(end_date="2030-03-04"))

    assert form.is_valid()
    assert form.cleaned_data["end_date"] is None


def test_an_end_date_before_the_date_is_refused():
    form = EventForm(_data(end_date="2030-03-03"))

    assert not form.is_valid()
    assert form.errors["end_date"] == ["End date must be after the date."]


def test_over_several_days_the_end_time_may_be_before_the_start_time():
    form = EventForm(_data(end_date="2030-03-06", start_time="14:00", end_time="10:00"))

    assert form.is_valid()


def test_on_one_day_the_end_time_must_still_follow_the_start_time():
    form = EventForm(_data(end_date="2030-03-04", start_time="14:00", end_time="10:00"))

    assert not form.is_valid()
    assert "end_time" in form.errors


def test_the_form_saves_the_span(client):
    client.post(reverse("calendar:add"), _data(end_date="2030-03-06"))

    event = Event.objects.get(description="Conference")
    assert event.end_date == date(2030, 3, 6)
    assert event.last_date == date(2030, 3, 6)


# --- the views -------------------------------------------------------------


def test_the_feed_ends_an_all_day_span_the_day_after_its_last(client, user):
    event = Event.objects.create(
        user=user, date=date(2030, 3, 4), end_date=date(2030, 3, 6), description="C"
    )

    row = _feed(client)[str(event.id)]

    assert row["start"] == "2030-03-04"
    assert row["end"] == "2030-03-07"
    assert row["allDay"] is True


def test_the_feed_ends_a_timed_span_on_its_last_day(client, user):
    event = Event.objects.create(
        user=user,
        date=date(2030, 3, 4),
        end_date=date(2030, 3, 6),
        start_time=time(9, 0),
        end_time=time(17, 0),
        description="C",
    )

    row = _feed(client)[str(event.id)]

    assert row["start"] == "2030-03-04T09:00:00"
    assert row["end"] == "2030-03-06T17:00:00"


def test_a_span_that_began_before_the_range_is_still_in_it(client, user):
    straddling = Event.objects.create(
        user=user, date=date(2030, 2, 27), end_date=date(2030, 3, 2), description="C"
    )
    before = Event.objects.create(
        user=user, date=date(2030, 2, 20), end_date=date(2030, 2, 22), description="B"
    )
    one_day_before = Event.objects.create(
        user=user, date=date(2030, 2, 28), description="D"
    )

    feed = _feed(client)

    assert str(straddling.id) in feed
    assert str(before.id) not in feed
    assert str(one_day_before.id) not in feed


def test_the_list_shows_the_range_and_the_days(client, user):
    Event.objects.create(
        user=user, date=date(2030, 3, 4), end_date=date(2030, 3, 6), description="C"
    )
    client.post(reverse("calendar:view-mode", args=["list"]))

    response = client.get(reverse("calendar:list"))

    assert response.context["objects"][0].duration_days == 3
    html = response.content.decode()
    assert "2030-03-04" in html
    assert "– 2030-03-06" in html
    assert "3 days" in html


def test_a_span_in_progress_is_upcoming(client, user):
    today = timezone.localdate()
    in_progress = Event.objects.create(
        user=user,
        date=today - timedelta(days=2),
        end_date=today + timedelta(days=2),
        description="Now",
    )
    over = Event.objects.create(
        user=user,
        date=today - timedelta(days=5),
        end_date=today - timedelta(days=3),
        description="Done",
    )
    client.post(reverse("calendar:view-mode", args=["list"]))

    assert list(client.get(reverse("calendar:list")).context["objects"]) == [
        in_progress
    ]

    client.post(reverse("calendar:filter"), {"period": "past"})
    assert list(client.get(reverse("calendar:list")).context["objects"]) == [over]


# --- drag and resize -------------------------------------------------------


def _quick(client, event, **body):
    return client.post(
        reverse("calendar:quick-update", args=[event.id]),
        json.dumps(body),
        content_type="application/json",
    )


def test_a_resize_sets_the_end_date(client, event):
    assert (
        _quick(client, event, date="2030-03-04", end_date="2030-03-06").status_code
        == 204
    )

    event.refresh_from_db()
    assert event.end_date == date(2030, 3, 6)


def test_a_resize_back_to_one_day_clears_it(client, user):
    event = Event.objects.create(
        user=user, date=date(2030, 3, 4), end_date=date(2030, 3, 6), description="C"
    )

    _quick(client, event, date="2030-03-04", end_date=None)
    event.refresh_from_db()
    assert event.end_date is None

    event.end_date = date(2030, 3, 6)
    event.save()
    _quick(client, event, date="2030-03-04", end_date="2030-03-04")
    event.refresh_from_db()
    assert event.end_date is None


def test_a_drag_keeps_the_span(client, user):
    event = Event.objects.create(
        user=user, date=date(2030, 3, 4), end_date=date(2030, 3, 6), description="C"
    )

    _quick(client, event, date="2030-03-11", end_date="2030-03-13")

    event.refresh_from_db()
    assert (event.date, event.end_date) == (date(2030, 3, 11), date(2030, 3, 13))


@pytest.mark.parametrize("end_date", ["2030-03-03", "March 6", 6])
def test_an_unusable_end_date_is_refused(client, event, end_date):
    response = _quick(client, event, date="2030-03-04", end_date=end_date)

    assert response.status_code == 400
    event.refresh_from_db()
    assert str(event.date) == "2022-12-28"
    assert event.end_date is None


# --- Google ----------------------------------------------------------------


class FakeGoogle:
    def __init__(self):
        self.sent = []

    def events(self):
        return self

    def insert(self, calendarId, body):
        self.sent.append(body)
        return self

    def execute(self):
        return {"id": "google-1"}


@pytest.fixture
def remote(monkeypatch, user):
    fake = FakeGoogle()
    user.google_credentials = '{"token": "x"}'
    user.calendar_sync = True
    user.save()
    monkeypatch.setattr(google, "build_service", lambda user: fake)
    return fake


def test_an_all_day_span_is_pushed_with_an_exclusive_end(remote, user):
    event = Event.objects.create(
        user=user, date=date(2030, 3, 4), end_date=date(2030, 3, 6), description="C"
    )

    sync.push_event(event)

    assert remote.sent[0]["start"] == {"date": "2030-03-04"}
    assert remote.sent[0]["end"] == {"date": "2030-03-07"}


def test_a_timed_span_is_pushed_ending_on_its_last_day(remote, user):
    event = Event.objects.create(
        user=user,
        date=date(2030, 3, 4),
        end_date=date(2030, 3, 6),
        start_time=time(9, 0),
        end_time=time(17, 0),
        description="C",
    )

    sync.push_event(event)

    assert remote.sent[0]["start"]["dateTime"] == "2030-03-04T09:00:00"
    assert remote.sent[0]["end"]["dateTime"] == "2030-03-06T17:00:00"


def test_an_all_day_span_is_pulled_with_its_last_day():
    data = google._parse_google_event(
        {"start": {"date": "2030-03-04"}, "end": {"date": "2030-03-07"}}
    )

    assert data["date"] == date(2030, 3, 4)
    assert data["end_date"] == date(2030, 3, 6)


def test_a_one_day_all_day_event_is_pulled_with_no_end_date():
    data = google._parse_google_event(
        {"start": {"date": "2030-03-04"}, "end": {"date": "2030-03-05"}}
    )

    assert data["end_date"] is None


def test_a_timed_span_is_pulled_with_its_last_day():
    data = google._parse_google_event(
        {
            "start": {"dateTime": "2030-03-04T09:00:00-05:00"},
            "end": {"dateTime": "2030-03-06T17:00:00-05:00"},
        }
    )

    assert data["date"] == date(2030, 3, 4)
    assert data["end_date"] == date(2030, 3, 6)
    assert data["end_time"] == time(17, 0)


def test_a_timed_event_on_one_day_is_pulled_with_no_end_date():
    data = google._parse_google_event(
        {
            "start": {"dateTime": "2030-03-04T09:00:00-05:00"},
            "end": {"dateTime": "2030-03-04T17:00:00-05:00"},
        }
    )

    assert data["end_date"] is None


def test_a_span_shortened_on_google_is_shortened_here(user):
    event = Event.objects.create(
        user=user,
        date=date(2030, 3, 4),
        end_date=date(2030, 3, 6),
        description="C",
        google_id="google-1",
    )
    Event.objects.filter(pk=event.pk).update(google_synced_at=event.updated_at)

    google._process_google_event(
        user,
        {
            "id": "google-1",
            "summary": "C",
            "start": {"date": "2030-03-04"},
            "end": {"date": "2030-03-05"},
        },
    )

    event.refresh_from_db()
    assert event.end_date is None
