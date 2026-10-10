"""Task notifications: set on the task, inherited by a recurring task's
instances, shown and sent where the user is, and the command that sends
them."""

from datetime import date, datetime, time
from io import StringIO
from zoneinfo import ZoneInfo

import pytest
from django.core.management import call_command
from django.urls import reverse

from apps.tasks import reminders
from apps.tasks.models import Task, TaskReminder

pytestmark = pytest.mark.django_db

EASTERN = "America/New_York"
DENVER = "America/Denver"


def _in(zone, *args):
    return datetime(*args, tzinfo=ZoneInfo(zone))


@pytest.fixture
def timed(user, folder):
    return Task.objects.create(
        user=user,
        folder=folder,
        title="Call the dentist",
        due_date=date(2030, 3, 4),
        due_time=time(14, 0),
    )


@pytest.fixture
def dated(user):
    return Task.objects.create(user=user, title="Pay rent", due_date=date(2030, 3, 4))


@pytest.fixture
def undated(user):
    return Task.objects.create(user=user, title="Someday")


# --- when and how it reads -------------------------------------------------


def test_a_timed_task_counts_back_from_its_due_moment(timed):
    reminder = TaskReminder(task=timed, amount=30, unit="minutes")

    assert reminder.fire_at == _in(EASTERN, 2030, 3, 4, 13, 30)
    assert reminder.describe() == "30 minutes before"


def test_a_dated_task_goes_out_at_a_time_of_day(dated):
    reminder = TaskReminder(task=dated, amount=1, unit="days", time=time(8, 0))

    assert reminder.fire_at == _in(EASTERN, 2030, 3, 3, 8, 0)
    assert reminder.describe() == "1 day before at 8:00 AM"


def test_an_undated_task_has_no_moment(undated):
    assert TaskReminder(task=undated, amount=1, unit="days").fire_at is None


def test_a_due_time_is_a_moment_in_the_tasks_zone(user):
    task = Task.objects.create(
        user=user,
        title="Dinner",
        due_date=date(2030, 3, 4),
        due_time=time(19, 0),
        time_zone=DENVER,
    )

    assert task.due_at == _in(EASTERN, 2030, 3, 4, 21, 0)
    assert task.shown.due_time == time(21, 0)
    assert task.in_zone(DENVER).due_time == time(19, 0)


# --- the edit form ---------------------------------------------------------


def test_the_form_lists_notifications_and_offers_to_add_one(client, timed):
    TaskReminder.objects.create(task=timed, amount=30, unit="minutes")

    html = client.get(reverse("tasks-form", args=[timed.id])).content.decode()

    assert "30 minutes before" in html
    assert reverse("tasks-reminder-add", args=[timed.id]) in html
    assert 'name="time"' not in html


def test_a_dated_tasks_form_offers_days_weeks_and_a_time(client, dated):
    html = client.get(reverse("tasks-form", args=[dated.id])).content.decode()

    assert 'name="time"' in html
    assert 'value="days"' in html
    assert 'value="minutes"' not in html


def test_an_undated_task_asks_for_a_due_date_first(client, undated):
    html = client.get(reverse("tasks-form", args=[undated.id])).content.decode()

    assert "Set a due date to add notifications" in html
    assert 'name="unit"' not in html

    response = client.post(
        reverse("tasks-reminder-add", args=[undated.id]), {"amount": 1, "unit": "days"}
    )
    assert response.status_code == 200
    assert not undated.reminders.exists()


def test_adding_and_removing_a_notification(client, timed):
    response = client.post(
        reverse("tasks-reminder-add", args=[timed.id]), {"amount": 2, "unit": "hours"}
    )
    assert response.status_code == 200
    assert "2 hours before" in response.content.decode()
    reminder = timed.reminders.get()
    assert (reminder.amount, reminder.unit, reminder.time) == (2, "hours", None)

    response = client.post(
        reverse("tasks-reminder-delete", args=[timed.id, reminder.id])
    )
    assert response.status_code == 200
    assert "No notifications" in response.content.decode()
    assert not timed.reminders.exists()


def test_a_notification_goes_by_the_channel_chosen(client, timed):
    response = client.post(
        reverse("tasks-reminder-add", args=[timed.id]),
        {"amount": 1, "unit": "days", "channel": "home"},
    )

    assert "Homepage" in response.content.decode()
    assert timed.reminders.get().channel == "home"


def test_the_users_default_channel_is_offered_first_and_push_once_set_up(
    client, user, timed
):
    html = client.get(reverse("tasks-form", args=[timed.id])).content.decode()
    assert '<option value="email" selected>Email</option>' in html
    assert 'value="ntfy"' not in html

    user.notify_by = "ntfy"
    user.ntfy_topic = "cpl-secret-topic"
    user.save()
    html = client.get(reverse("tasks-form", args=[timed.id])).content.decode()
    assert '<option value="ntfy" selected>Push</option>' in html

    client.post(
        reverse("tasks-reminder-add", args=[timed.id]), {"amount": 1, "unit": "days"}
    )
    assert timed.reminders.get().channel == "ntfy"


def test_a_dated_task_refuses_minutes(client, dated):
    response = client.post(
        reverse("tasks-reminder-add", args=[dated.id]),
        {"amount": 30, "unit": "minutes"},
    )

    assert "days or weeks" in response.content.decode()
    assert not dated.reminders.exists()


def test_another_users_task_is_not_found(client, timed):
    from accounts.models import CustomUser

    other = CustomUser.objects.create_user("Nico", "nico@gmail.com", "clawboy")
    theirs = Task.objects.create(user=other, title="Theirs", due_date=date(2030, 3, 4))

    response = client.post(
        reverse("tasks-reminder-add", args=[theirs.id]), {"amount": 1, "unit": "days"}
    )

    assert response.status_code == 404


def test_the_form_opens_where_the_user_is_and_saving_keeps_the_moment(
    client, user, folder
):
    task = Task.objects.create(
        user=user,
        folder=folder,
        title="Dinner",
        due_date=date(2030, 3, 4),
        due_time=time(19, 0),
        time_zone=DENVER,
    )

    form = client.get(reverse("tasks-form", args=[task.id])).context["form"]
    assert form.initial["due_time"] == time(21, 0)

    client.post(
        reverse("tasks-form", args=[task.id]),
        {
            "title": "Dinner",
            "due_date": "2030-03-04",
            "due_time": "21:00",
            "priority": 5,
            "status": 0,
            "archived": "False",
            "folder": folder.id,
        },
    )

    task.refresh_from_db()
    assert task.time_zone == EASTERN
    assert task.due_at == _in(DENVER, 2030, 3, 4, 19, 0)


# --- recurring tasks -------------------------------------------------------


def test_an_instances_notification_passes_to_its_template_and_onward(client, user):
    template = Task.objects.create(
        user=user,
        title="Take out trash",
        is_recurring=True,
        repeat_frequency="weekly",
        repeat_start=date(2030, 3, 4),
        due_date=date(2030, 3, 4),
        due_time=time(19, 0),
    )
    instance = Task.objects.create(
        user=user,
        title="Take out trash",
        due_date=date(2030, 3, 4),
        due_time=time(19, 0),
        parent_task=template,
    )

    client.post(
        reverse("tasks-reminder-add", args=[instance.id]),
        {"amount": 1, "unit": "hours", "channel": "home"},
    )
    assert template.reminders.filter(amount=1, unit="hours", channel="home").exists()

    next_instance = Task.objects.create(
        user=user,
        title="Take out trash",
        due_date=date(2030, 3, 11),
        due_time=time(19, 0),
        parent_task=template,
    )
    next_instance.copy_reminders_from(template)
    assert next_instance.reminders.get().describe() == "1 hour before"
    assert next_instance.reminders.get().channel == "home"

    reminder = instance.reminders.get()
    client.post(reverse("tasks-reminder-delete", args=[instance.id, reminder.id]))
    assert not template.reminders.exists()


def test_the_recurring_command_gives_new_instances_the_notifications(user):
    template = Task.objects.create(
        user=user,
        title="Water plants",
        is_recurring=True,
        repeat_frequency="daily",
        repeat_start=date(2030, 3, 4),
        due_date=date(2030, 3, 4),
        due_time=time(8, 0),
        time_zone=DENVER,
    )
    TaskReminder.objects.create(task=template, amount=15, unit="minutes")

    call_command("create_recurring_tasks", stdout=StringIO())

    instance = Task.objects.get(parent_task=template)
    assert instance.time_zone == DENVER
    assert instance.reminders.get().describe() == "15 minutes before"


# --- sending ---------------------------------------------------------------


def test_a_due_notification_is_sent_once(timed, mailoutbox):
    reminder = TaskReminder.objects.create(task=timed, amount=30, unit="minutes")
    due = _in(EASTERN, 2030, 3, 4, 13, 31)

    assert reminders.send_due(now=due) == (1, 0)
    assert mailoutbox[0].subject == "Call the dentist - due Monday, March 4 at 2:00 PM"
    assert "Folder: Current" in mailoutbox[0].body
    reminder.refresh_from_db()
    assert reminder.sent_for == _in(EASTERN, 2030, 3, 4, 13, 30)

    assert reminders.send_due(now=due) == (0, 0)
    assert len(mailoutbox) == 1


def test_a_completed_or_template_task_is_not_notified(user, timed, mailoutbox):
    TaskReminder.objects.create(task=timed, amount=30, unit="minutes")
    timed.status = 1
    timed.save()
    template = Task.objects.create(
        user=user,
        title="Template",
        is_recurring=True,
        due_date=date(2030, 3, 4),
        due_time=time(14, 0),
    )
    TaskReminder.objects.create(task=template, amount=30, unit="minutes")

    assert reminders.send_due(now=_in(EASTERN, 2030, 3, 4, 13, 31)) == (0, 0)
    assert mailoutbox == []


def test_a_task_with_no_time_is_notified_at_the_hour_where_the_user_is(
    user, dated, mailoutbox
):
    user.time_zone = DENVER
    user.save()
    TaskReminder.objects.create(task=dated, amount=0, unit="days", time=time(9, 0))

    assert reminders.send_due(now=_in(EASTERN, 2030, 3, 4, 10, 59)) == (0, 0)
    assert reminders.send_due(now=_in(EASTERN, 2030, 3, 4, 11, 0)) == (1, 0)
    assert mailoutbox[0].subject == "Pay rent - due Monday, March 4"


def test_a_task_without_a_due_time_gets_no_automatic_notification(
    user, dated, mailoutbox
):
    """The old command mailed every task due today; now only a set
    notification does."""
    assert reminders.send_due(now=_in(EASTERN, 2030, 3, 4, 9, 0)) == (0, 0)
    assert mailoutbox == []


def test_the_command_sends_the_notifications_due(user, timed, monkeypatch):
    monkeypatch.setattr(reminders, "send_due", lambda now=None: (2, 0))
    out = StringIO()

    call_command("send_task_reminders", stdout=out)

    assert "Sent 2 notification(s), 0 error(s)" in out.getvalue()
