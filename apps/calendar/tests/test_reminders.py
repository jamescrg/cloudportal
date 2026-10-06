"""Event notifications: when they go out, how they read, how they are
added and removed on the edit form, and what the cron command sends."""

from datetime import date, datetime, time, timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.calendar import reminders
from apps.calendar.models import Event, EventReminder

pytestmark = pytest.mark.django_db


def _aware(*args):
    return timezone.make_aware(datetime(*args))


@pytest.fixture
def timed(user):
    return Event.objects.create(
        user=user,
        date=date(2030, 3, 4),
        start_time=time(14, 0),
        end_time=time(15, 0),
        description="Dentist",
        location="100 Main St",
    )


@pytest.fixture
def all_day(user):
    return Event.objects.create(user=user, date=date(2030, 3, 4), description="Trip")


# --- when and how it reads -------------------------------------------------


@pytest.mark.parametrize(
    "amount, unit, fire_at, words",
    [
        (30, "minutes", _aware(2030, 3, 4, 13, 30), "30 minutes before"),
        (1, "hours", _aware(2030, 3, 4, 13, 0), "1 hour before"),
        (2, "days", _aware(2030, 3, 2, 14, 0), "2 days before"),
        (1, "weeks", _aware(2030, 2, 25, 14, 0), "1 week before"),
        (0, "minutes", _aware(2030, 3, 4, 14, 0), "At the start"),
    ],
)
def test_a_timed_event_counts_back_from_its_start(timed, amount, unit, fire_at, words):
    reminder = EventReminder(event=timed, amount=amount, unit=unit)

    assert reminder.fire_at == fire_at
    assert reminder.describe() == words


@pytest.mark.parametrize(
    "amount, unit, at, fire_at, words",
    [
        (1, "days", time(9, 0), _aware(2030, 3, 3, 9, 0), "1 day before at 9:00 AM"),
        (0, "days", time(7, 30), _aware(2030, 3, 4, 7, 30), "That day at 7:30 AM"),
        (1, "weeks", None, _aware(2030, 2, 25, 9, 0), "1 week before at 9:00 AM"),
    ],
)
def test_an_all_day_event_goes_out_at_a_time_of_day(
    all_day, amount, unit, at, fire_at, words
):
    reminder = EventReminder(event=all_day, amount=amount, unit=unit, time=at)

    assert reminder.fire_at == fire_at
    assert reminder.describe() == words


# --- the edit form ---------------------------------------------------------


def test_the_edit_form_lists_notifications_and_offers_to_add_one(client, timed):
    EventReminder.objects.create(event=timed, amount=30, unit="minutes")

    html = client.get(reverse("calendar:edit", args=[timed.id])).content.decode()

    assert "30 minutes before" in html
    assert reverse("calendar:reminder-add", args=[timed.id]) in html
    assert 'name="time"' not in html


def test_an_all_day_events_form_offers_days_weeks_and_a_time(client, all_day):
    html = client.get(reverse("calendar:edit", args=[all_day.id])).content.decode()

    assert 'name="time"' in html
    assert 'value="days"' in html
    assert 'value="minutes"' not in html


def test_the_add_form_has_no_notifications_section(client):
    assert "Notifications" not in client.get(reverse("calendar:add")).content.decode()


def test_adding_a_notification(client, timed):
    response = client.post(
        reverse("calendar:reminder-add", args=[timed.id]),
        {"amount": 2, "unit": "hours"},
    )

    assert response.status_code == 200
    assert "2 hours before" in response.content.decode()
    reminder = timed.reminders.get()
    assert (reminder.amount, reminder.unit, reminder.time) == (2, "hours", None)


def test_adding_to_an_all_day_event_keeps_the_time(client, all_day):
    client.post(
        reverse("calendar:reminder-add", args=[all_day.id]),
        {"amount": 1, "unit": "days", "time": "08:00"},
    )

    assert all_day.reminders.get().time == time(8, 0)


def test_an_all_day_event_refuses_minutes(client, all_day):
    response = client.post(
        reverse("calendar:reminder-add", args=[all_day.id]),
        {"amount": 30, "unit": "minutes"},
    )

    assert response.status_code == 200
    assert "days or weeks" in response.content.decode()
    assert not all_day.reminders.exists()


def test_removing_a_notification(client, timed):
    reminder = EventReminder.objects.create(event=timed, amount=30, unit="minutes")

    response = client.post(
        reverse("calendar:reminder-delete", args=[timed.id, reminder.id])
    )

    assert response.status_code == 200
    assert "No notifications" in response.content.decode()
    assert not timed.reminders.exists()


def test_another_users_event_cannot_be_given_a_notification(client, other_user):
    theirs = Event.objects.create(
        user=other_user, date=date(2030, 3, 4), description="T"
    )

    response = client.post(
        reverse("calendar:reminder-add", args=[theirs.id]),
        {"amount": 1, "unit": "days"},
    )

    assert response.status_code == 404
    assert not theirs.reminders.exists()


def test_deleting_the_event_removes_its_notifications(client, timed):
    EventReminder.objects.create(event=timed, amount=30, unit="minutes")

    client.post(reverse("calendar:delete", args=[timed.id]))

    assert not EventReminder.objects.exists()


# --- sending ---------------------------------------------------------------


def test_a_due_notification_is_sent_once(timed, mailoutbox):
    reminder = EventReminder.objects.create(event=timed, amount=30, unit="minutes")
    due = _aware(2030, 3, 4, 13, 31)

    assert reminders.send_due(now=due) == (1, 0)
    assert mailoutbox[0].subject == "Dentist - Monday, March 4 at 2:00 PM"
    assert mailoutbox[0].to == ["ollie@gmail.com"]
    assert "Location: 100 Main St" in mailoutbox[0].body
    reminder.refresh_from_db()
    assert reminder.sent_for == _aware(2030, 3, 4, 13, 30)

    assert reminders.send_due(now=due + timedelta(minutes=5)) == (0, 0)
    assert len(mailoutbox) == 1


def test_a_notification_not_yet_due_waits(timed, mailoutbox):
    EventReminder.objects.create(event=timed, amount=30, unit="minutes")

    assert reminders.send_due(now=_aware(2030, 3, 4, 13, 0)) == (0, 0)
    assert mailoutbox == []


def test_a_notification_long_past_is_let_go(timed, mailoutbox):
    reminder = EventReminder.objects.create(event=timed, amount=30, unit="minutes")

    assert reminders.send_due(now=_aware(2030, 3, 4, 18, 0)) == (0, 0)
    assert mailoutbox == []
    reminder.refresh_from_db()
    assert reminder.sent_for == _aware(2030, 3, 4, 13, 30)


def test_a_moved_event_is_notified_again(timed, mailoutbox):
    EventReminder.objects.create(event=timed, amount=30, unit="minutes")
    reminders.send_due(now=_aware(2030, 3, 4, 13, 31))

    timed.date = date(2030, 3, 5)
    timed.save()

    assert reminders.send_due(now=_aware(2030, 3, 5, 13, 31)) == (1, 0)
    assert len(mailoutbox) == 2


def test_the_notification_goes_to_the_notification_address(user, timed, mailoutbox):
    user.notification_email = "phone@gmail.com"
    user.save()
    EventReminder.objects.create(event=timed, amount=0, unit="minutes")

    reminders.send_due(now=_aware(2030, 3, 4, 14, 0))

    assert mailoutbox[0].to == ["phone@gmail.com"]


def test_an_all_day_notification_goes_out_at_its_time(all_day, mailoutbox):
    EventReminder.objects.create(event=all_day, amount=1, unit="days", time=time(9, 0))

    assert reminders.send_due(now=_aware(2030, 3, 3, 8, 59)) == (0, 0)
    assert reminders.send_due(now=_aware(2030, 3, 3, 9, 0)) == (1, 0)
    assert mailoutbox[0].subject == "Trip - Monday, March 4"


def test_the_command_reports_what_it_sent(timed, mailoutbox, monkeypatch):
    from io import StringIO

    from django.core.management import call_command

    monkeypatch.setattr(reminders, "send_due", lambda now=None: (3, 1))
    out = StringIO()

    call_command("send_event_reminders", stdout=out)

    assert "Sent 3 notification(s), 1 error(s)" in out.getvalue()
