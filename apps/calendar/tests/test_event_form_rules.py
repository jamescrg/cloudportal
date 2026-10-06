"""What Add Event and Edit Event accept, and how the form opens.

A blank description is a form error, not a server error. An event with a
start and no end gets an end on the same day. A click on a calendar time
slot opens the form on that day and time.
"""

from datetime import date, time

import pytest
from django.urls import reverse

from apps.calendar.events import default_end_time
from apps.calendar.models import Event

pytestmark = pytest.mark.django_db


def _data(**changes):
    return {"date": "2030-03-04", "description": "Dentist appointment"} | changes


# --- description -----------------------------------------------------------


def test_blank_description_is_a_form_error(client):
    response = client.post(reverse("calendar:add"), _data(description=""))

    assert response.status_code == 200
    assert "4 or more" in response.context["form"].errors["description"][0]
    assert not Event.objects.exists()


# --- the end time given to a start with no end -----------------------------


@pytest.mark.parametrize(
    "start, end",
    [
        (time(9, 0), time(10, 0)),
        (time(22, 59), time(23, 59)),
        (time(23, 30), time(23, 59)),
        (time(23, 59), None),
    ],
)
def test_default_end_time_stays_on_the_same_day(start, end):
    assert default_end_time(start) == end


def test_start_with_no_end_runs_for_an_hour(client):
    client.post(reverse("calendar:add"), _data(start_time="09:00"))

    event = Event.objects.get(description="Dentist appointment")
    assert event.start_time == time(9, 0)
    assert event.end_time == time(10, 0)


def test_late_start_saves_with_an_end_after_it(client):
    client.post(reverse("calendar:add"), _data(start_time="23:30"))

    event = Event.objects.get(description="Dentist appointment")
    assert event.end_time == time(23, 59)


def test_edit_gives_a_late_start_an_end_after_it(client, event):
    client.post(reverse("calendar:edit", args=[event.id]), _data(start_time="23:45"))

    event.refresh_from_db()
    assert event.end_time > event.start_time


# --- opening the form from the calendar ------------------------------------


def test_time_slot_click_carries_the_date_and_the_start_time(client):
    form = client.get(
        reverse("calendar:add"), {"date": "2030-03-04", "start_time": "14:30"}
    ).context["form"]

    assert form.initial["date"] == date(2030, 3, 4)
    assert form.initial["start_time"] == time(14, 30)


def test_a_date_time_in_the_date_still_lands_on_that_day(client):
    form = client.get(
        reverse("calendar:add"), {"date": "2030-03-04T14:30:00-05:00"}
    ).context["form"]

    assert form.initial["date"] == date(2030, 3, 4)


def test_day_click_carries_no_start_time(client):
    form = client.get(reverse("calendar:add"), {"date": "2030-03-04"}).context["form"]

    assert form.initial["date"] == date(2030, 3, 4)
    assert "start_time" not in form.initial


def test_an_unreadable_date_falls_back_to_today(client):
    from django.utils import timezone

    form = client.get(reverse("calendar:add"), {"date": "next tuesday"}).context["form"]

    assert form.initial["date"] == timezone.localdate()
