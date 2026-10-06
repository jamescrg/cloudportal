"""A timed event is a moment: its date and times plus the zone they were
entered in. The user carries the zone they are in now, reported by the
browser, and everything is read, shown and sent in it."""

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pytest
from django.urls import reverse

import apps.calendar.google as google
import apps.calendar.invitations as invitations
from apps.calendar import reminders
from apps.calendar.models import Event, EventReminder
from apps.calendar.tests.test_invitations import TIMED

pytestmark = pytest.mark.django_db

DENVER = "America/Denver"
EASTERN = "America/New_York"


def _in(zone, *args):
    return datetime(*args, tzinfo=ZoneInfo(zone))


@pytest.fixture
def denver_dinner(user):
    """Dinner at 7:00 PM in Denver, which is 9:00 PM in the East."""
    return Event.objects.create(
        user=user,
        date=date(2030, 3, 4),
        start_time=time(19, 0),
        end_time=time(20, 0),
        time_zone=DENVER,
        description="Dinner",
    )


# --- the model -------------------------------------------------------------


def test_an_event_is_a_moment_in_its_own_zone(denver_dinner):
    assert denver_dinner.start_at == _in(DENVER, 2030, 3, 4, 19, 0)
    assert denver_dinner.start_at == _in(EASTERN, 2030, 3, 4, 21, 0)
    assert denver_dinner.end_at == _in(DENVER, 2030, 3, 4, 20, 0)


def test_an_event_reads_differently_from_another_zone(denver_dinner):
    shown = denver_dinner.in_zone(EASTERN)

    assert (shown.date, shown.start_time, shown.end_time) == (
        date(2030, 3, 4),
        time(21, 0),
        time(22, 0),
    )
    assert shown.end_date is None


def test_a_late_event_can_land_on_the_next_day_elsewhere(user):
    event = Event.objects.create(
        user=user,
        date=date(2030, 3, 4),
        start_time=time(23, 0),
        end_time=time(23, 30),
        time_zone=DENVER,
        description="Late call",
    )

    shown = event.in_zone("Europe/London")

    assert shown.date == date(2030, 3, 5)
    assert shown.start_time == time(6, 0)


def test_an_all_day_event_reads_the_same_everywhere(user):
    event = Event.objects.create(
        user=user, date=date(2030, 3, 4), end_date=date(2030, 3, 6), description="Trip"
    )

    shown = event.in_zone("Asia/Tokyo")

    assert (shown.date, shown.end_date, shown.start_time) == (
        date(2030, 3, 4),
        date(2030, 3, 6),
        None,
    )


def test_an_unknown_zone_falls_back_to_the_apps(user):
    event = Event(
        user=user,
        date=date(2030, 3, 4),
        start_time=time(9, 0),
        time_zone="Mars/Olympus",
    )

    assert event.start_at == _in(EASTERN, 2030, 3, 4, 9, 0)


# --- where the user is -----------------------------------------------------


def test_the_browser_reports_the_zone(client, user):
    response = client.post(reverse("settings-time-zone"), {"time_zone": DENVER})

    assert response.status_code == 204
    user.refresh_from_db()
    assert user.time_zone == DENVER


def test_a_name_that_is_not_a_zone_is_refused(client, user):
    response = client.post(reverse("settings-time-zone"), {"time_zone": "Mountain"})

    assert response.status_code == 400
    user.refresh_from_db()
    assert user.time_zone == EASTERN


def test_the_page_carries_the_zone_for_the_browser_to_compare(client, user):
    html = client.get("/calendar/").content.decode()

    assert f'data-time-zone="{EASTERN}"' in html
    assert "js/time-zone.js" in html


def test_the_settings_tab_shows_the_zone(client):
    assert EASTERN in client.get(reverse("settings-calendar")).content.decode()


# --- typing, showing and dragging ------------------------------------------


def test_a_typed_event_is_in_the_users_current_zone(client, user):
    user.time_zone = DENVER
    user.save()

    client.post(
        reverse("calendar:add"),
        {"date": "2030-03-04", "start_time": "19:00", "description": "Dinner"},
    )

    event = Event.objects.get(description="Dinner")
    assert event.time_zone == DENVER
    assert event.start_at == _in(EASTERN, 2030, 3, 4, 21, 0)


def test_the_list_shows_events_where_the_user_is(client, user, denver_dinner):
    client.post(reverse("calendar:view-mode", args=["list"]))

    assert "9:00 PM" in client.get(reverse("calendar:list")).content.decode()

    user.time_zone = DENVER
    user.save()
    assert "7:00 PM" in client.get(reverse("calendar:list")).content.decode()


def test_the_feed_sends_each_event_as_a_moment(client, denver_dinner):
    feed = client.get(
        reverse("calendar:api"), {"start": "2030-03-01", "end": "2030-03-31"}
    ).json()

    assert feed[0]["start"] == "2030-03-04T19:00:00-07:00"
    assert feed[0]["end"] == "2030-03-04T20:00:00-07:00"


def test_the_edit_form_opens_where_the_user_is_and_keeps_the_moment(
    client, user, denver_dinner
):
    form = client.get(reverse("calendar:edit", args=[denver_dinner.id])).context["form"]
    assert form.initial["start_time"] == time(21, 0)

    client.post(
        reverse("calendar:edit", args=[denver_dinner.id]),
        {
            "date": "2030-03-04",
            "start_time": "21:00",
            "end_time": "22:00",
            "description": "Dinner",
        },
    )

    denver_dinner.refresh_from_db()
    assert denver_dinner.time_zone == EASTERN
    assert denver_dinner.start_time == time(21, 0)
    assert denver_dinner.start_at == _in(DENVER, 2030, 3, 4, 19, 0)


def test_a_drag_names_the_browsers_zone(client, denver_dinner):
    import json

    response = client.post(
        reverse("calendar:quick-update", args=[denver_dinner.id]),
        json.dumps(
            {
                "date": "2030-03-05",
                "start_time": "21:00:00",
                "end_time": "22:00:00",
                "time_zone": EASTERN,
            }
        ),
        content_type="application/json",
    )

    assert response.status_code == 204
    denver_dinner.refresh_from_db()
    assert denver_dinner.time_zone == EASTERN
    assert denver_dinner.start_at == _in(DENVER, 2030, 3, 5, 19, 0)


def test_a_drag_with_an_unknown_zone_is_refused(client, denver_dinner):
    import json

    response = client.post(
        reverse("calendar:quick-update", args=[denver_dinner.id]),
        json.dumps({"date": "2030-03-05", "time_zone": "Mountain"}),
        content_type="application/json",
    )

    assert response.status_code == 400
    denver_dinner.refresh_from_db()
    assert str(denver_dinner.date) == "2030-03-04"


# --- notifications ---------------------------------------------------------


def test_a_notification_fires_at_the_moment_wherever_it_was_set(
    denver_dinner, mailoutbox
):
    EventReminder.objects.create(event=denver_dinner, amount=30, unit="minutes")

    assert reminders.send_due(now=_in(EASTERN, 2030, 3, 4, 20, 29)) == (0, 0)
    assert reminders.send_due(now=_in(EASTERN, 2030, 3, 4, 20, 30)) == (1, 0)
    # The user is in the East, so that is how the note reads
    assert mailoutbox[0].subject == "Dinner - Monday, March 4 at 9:00 PM"


def test_an_all_day_notification_goes_out_at_the_hour_where_the_user_is(
    user, mailoutbox
):
    user.time_zone = DENVER
    user.save()
    event = Event.objects.create(user=user, date=date(2030, 3, 4), description="Trip")
    EventReminder.objects.create(event=event, amount=1, unit="days", time=time(9, 0))

    assert reminders.send_due(now=_in(EASTERN, 2030, 3, 3, 10, 59)) == (0, 0)
    assert reminders.send_due(now=_in(EASTERN, 2030, 3, 3, 11, 0)) == (1, 0)


# --- Google and invitations ------------------------------------------------


def test_the_push_names_the_events_zone(denver_dinner):
    body = google._event_body(denver_dinner)

    assert body["start"] == {"dateTime": "2030-03-04T19:00:00", "timeZone": DENVER}
    assert body["end"]["timeZone"] == DENVER


def test_a_pull_keeps_googles_zone():
    data = google._parse_google_event(
        {
            "start": {"dateTime": "2030-03-05T02:00:00Z", "timeZone": DENVER},
            "end": {"dateTime": "2030-03-05T03:00:00Z", "timeZone": DENVER},
        },
        EASTERN,
    )

    assert data["time_zone"] == DENVER
    assert data["date"] == date(2030, 3, 4)
    assert data["start_time"] == time(19, 0)


def test_a_pull_without_a_zone_reads_in_the_users(user):
    user.time_zone = DENVER
    user.save()
    user.google_credentials = '{"token": "x"}'
    user.calendar_sync = True
    user.save()

    google._process_google_event(
        user,
        {
            "id": "google-1",
            "summary": "Call",
            "start": {"dateTime": "2030-03-05T02:00:00Z"},
            "end": {"dateTime": "2030-03-05T03:00:00Z"},
        },
    )

    event = Event.objects.get(google_id="google-1")
    assert event.time_zone == DENVER
    assert event.start_time == time(19, 0)


def test_a_forwarded_invitation_is_read_where_the_user_is(user):
    user.time_zone = DENVER
    user.save()

    invitation = invitations.parse_invitation(TIMED, user.time_zone)
    _, event = invitations.post_invitation(user, invitation)

    # 14:00Z is 7:00 AM in Denver
    assert event.time_zone == DENVER
    assert event.start_time == time(7, 0)
    assert event.start_at == _in(EASTERN, 2030, 3, 4, 9, 0)
