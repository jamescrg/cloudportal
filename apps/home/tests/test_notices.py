"""Notifications sent to the home page: each is a card that stays until it
is closed, a task's with a Done button."""

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pytest
from django.urls import reverse

from apps.calendar import reminders as event_reminders
from apps.calendar.models import Event, EventReminder
from apps.common import notify
from apps.home.models import HomeNotice
from apps.tasks import reminders as task_reminders
from apps.tasks.models import Task, TaskReminder

pytestmark = pytest.mark.django_db


def _in(zone, *args):
    return datetime(*args, tzinfo=ZoneInfo(zone))


@pytest.fixture
def task(user):
    return Task.objects.create(
        user=user,
        title="Call the dentist",
        due_date=date(2030, 3, 4),
        due_time=time(14, 0),
        time_zone="America/New_York",
    )


@pytest.fixture
def card(user, task):
    return notify.task_reminder(user, task, "home") and HomeNotice.objects.get()


# --- what is posted ---------------------------------------------------------


def test_a_task_notification_to_the_home_page_is_a_card(user, task, mailoutbox):
    TaskReminder.objects.create(task=task, channel="home", amount=30, unit="minutes")

    sent = task_reminders.send_due(now=_in("America/New_York", 2030, 3, 4, 13, 31))

    assert sent == (1, 0)
    notice = HomeNotice.objects.get()
    assert (notice.kind, notice.task, notice.title) == (
        "task",
        task,
        "Call the dentist",
    )
    assert notice.line_list == ["Due Monday, March 4 at 2:00 PM"]
    assert notice.dismissed_at is None
    assert mailoutbox == []


def test_an_event_notification_to_the_home_page_is_a_card(user, mailoutbox):
    event = Event.objects.create(
        user=user,
        date=date(2030, 3, 4),
        start_time=time(9, 0),
        end_time=time(9, 30),
        description="Standup",
        location="Zoom",
        time_zone="America/New_York",
    )
    EventReminder.objects.create(event=event, channel="home", amount=1, unit="hours")

    sent = event_reminders.send_due(now=_in("America/New_York", 2030, 3, 4, 8, 1))

    assert sent == (1, 0)
    notice = HomeNotice.objects.get()
    assert (notice.kind, notice.event, notice.title) == ("event", event, "Standup")
    assert notice.line_list == ["Monday, March 4 at 9:00 AM – 9:30 AM", "Zoom"]
    assert mailoutbox == []


def test_a_thing_notified_again_brings_its_card_up_to_date(user, task, card):
    task.title = "Call the dentist back"
    task.save()

    notify.task_reminder(user, task, "home")

    assert HomeNotice.objects.count() == 1
    assert HomeNotice.objects.get().title == "Call the dentist back"


def test_a_closed_card_is_not_reopened_by_a_second_notification(user, task, card):
    card.dismiss()

    notify.task_reminder(user, task, "home")

    assert HomeNotice.objects.open().count() == 1
    assert HomeNotice.objects.count() == 2


def test_the_dev_machine_posts_cards_as_production_does(settings, user, task):
    settings.EMAIL_NOTIFICATIONS = False

    assert notify.task_reminder(user, task, "home") == {"success": True}
    assert HomeNotice.objects.open().exists()


# --- on the page ------------------------------------------------------------


def test_the_card_shows_on_the_home_page_until_closed(client, card):
    page = client.get(reverse("home")).content.decode()
    assert "Call the dentist" in page
    assert "Due Monday, March 4 at 2:00 PM" in page
    assert reverse("tasks-edit", args=[card.task_id]) in page

    response = client.post(reverse("home-notice-dismiss", args=[card.id]))

    assert response.status_code == 200 and response.content == b""
    card.refresh_from_db()
    assert card.dismissed_at is not None
    assert "Call the dentist" not in client.get(reverse("home")).content.decode()


def test_an_events_card_opens_the_calendar_on_its_day(client, user):
    event = Event.objects.create(
        user=user, date=date(2030, 3, 4), description="Trip", time_zone="UTC"
    )
    notify.event_reminder(user, event, "home")

    page = client.get(reverse("home")).content.decode()

    assert reverse("calendar:index") + "?date=2030-03-04" in page


def test_done_marks_the_task_done_and_closes_the_card(client, task, card):
    response = client.post(reverse("home-notice-done", args=[card.id]))

    assert response.status_code == 200
    task.refresh_from_db()
    assert task.status == 1
    card.refresh_from_db()
    assert card.dismissed_at is not None


def test_done_on_a_task_the_user_deletes_when_done(client, user, task, card):
    user.task_completion_mode = "delete"
    user.save()

    assert client.post(reverse("home-notice-done", args=[card.id])).status_code == 200

    assert not Task.objects.filter(pk=task.pk).exists()
    assert not HomeNotice.objects.exists()


def test_deleting_the_task_takes_its_card(task, card):
    task.delete()

    assert not HomeNotice.objects.exists()


def test_another_users_card_cannot_be_closed(client, card):
    from accounts.models import CustomUser

    other = CustomUser.objects.create_user(
        username="other", email="other@example.com", password="pw"
    )
    HomeNotice.objects.filter(pk=card.pk).update(user=other)

    assert (
        client.post(reverse("home-notice-dismiss", args=[card.id])).status_code == 404
    )
    assert client.post(reverse("home-notice-done", args=[card.id])).status_code == 404
    assert HomeNotice.objects.get().dismissed_at is None
