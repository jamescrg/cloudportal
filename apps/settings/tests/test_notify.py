"""Notifications by ntfy: the delivery setting, what is pushed, falling back
to email, and the Done button."""

from datetime import date, time, timedelta

import pytest
import requests
from django.urls import reverse
from django.utils import timezone

from apps.calendar.models import Event
from apps.common import notify
from apps.tasks.models import Task

pytestmark = pytest.mark.django_db


class FakeNtfy:
    """Stands in for ntfy's server: records each publish, or fails."""

    def __init__(self, fail=False):
        self.sent = []
        self.fail = fail

    def post(self, url, json=None, headers=None, timeout=None):
        if self.fail:
            raise requests.ConnectionError("ntfy is down")
        self.sent.append({"url": url, "json": json, "headers": headers or {}})

        class Response:
            def raise_for_status(self):
                pass

        return Response()


@pytest.fixture
def ntfy(monkeypatch):
    fake = FakeNtfy()
    monkeypatch.setattr(notify.requests, "post", fake.post)
    return fake


@pytest.fixture
def ntfy_user(user):
    user.notify_by = "ntfy"
    user.ntfy_topic = "cpl-secret-topic"
    user.time_zone = "America/New_York"
    user.save()
    return user


# --- the setting -----------------------------------------------------------


def test_choosing_ntfy_gives_a_long_random_topic(client, user):
    client.post(reverse("settings-notify-by"), {"notify_by": "ntfy"})

    user.refresh_from_db()
    assert user.notify_by == "ntfy"
    assert user.ntfy_topic.startswith("cpl-") and len(user.ntfy_topic) > 30


def test_choosing_the_home_page(client, user):
    client.post(reverse("settings-notify-by"), {"notify_by": "home"})

    user.refresh_from_db()
    assert user.notify_by == "home"


def test_choosing_ntfy_again_keeps_the_topic(client, ntfy_user):
    client.post(reverse("settings-notify-by"), {"notify_by": "email"})
    client.post(reverse("settings-notify-by"), {"notify_by": "ntfy"})

    ntfy_user.refresh_from_db()
    assert ntfy_user.ntfy_topic == "cpl-secret-topic"


def test_a_new_topic_replaces_the_old(client, ntfy_user):
    client.post(reverse("settings-ntfy-new-topic"))

    ntfy_user.refresh_from_db()
    assert ntfy_user.ntfy_topic != "cpl-secret-topic"


def test_the_server_must_be_an_address(client, ntfy_user):
    response = client.post(reverse("settings-ntfy"), {"ntfy_server": "not a url"})

    assert "Enter the server" in response.content.decode()
    ntfy_user.refresh_from_db()
    assert ntfy_user.ntfy_server == "https://ntfy.sh"


def test_the_page_offers_the_subscribe_link(client, ntfy_user):
    page = client.get(reverse("settings-notifications")).content.decode()

    assert "ntfy://ntfy.sh/cpl-secret-topic" in page


def test_a_test_is_pushed_with_the_saved_token(client, ntfy_user, ntfy):
    response = client.post(
        reverse("settings-ntfy-test"),
        {"ntfy_server": "https://push.example.com/", "ntfy_token": "tk_abc"},
    )

    assert response["Location"].endswith("?test=sent")
    sent = ntfy.sent[0]
    assert sent["url"] == "https://push.example.com"
    assert sent["json"]["topic"] == "cpl-secret-topic"
    assert sent["headers"]["Authorization"] == "Bearer tk_abc"


# --- what is pushed ----------------------------------------------------------


def test_a_task_reminder_is_pushed_with_open_and_done_buttons(
    ntfy_user, ntfy, mailoutbox
):
    task = Task.objects.create(
        user=ntfy_user,
        title="Call the dentist",
        due_date=date(2030, 3, 4),
        due_time=time(14, 0),
        time_zone="America/New_York",
    )

    assert notify.task_reminder(ntfy_user, task) == {"success": True}

    message = ntfy.sent[0]["json"]
    assert message["title"] == "Call the dentist"
    assert message["message"] == "Due Monday, March 4 at 2:00 PM"
    assert message["priority"] == 4
    labels = [action["label"] for action in message["actions"]]
    assert labels == ["Open", "Done"]
    assert "/tasks/notify/" in message["actions"][1]["url"]
    assert mailoutbox == []


def test_an_event_reminder_is_pushed(ntfy_user, ntfy):
    event = Event.objects.create(
        user=ntfy_user,
        date=date(2030, 3, 4),
        start_time=time(9, 0),
        end_time=time(9, 30),
        description="Standup",
        location="Zoom",
        time_zone="America/New_York",
    )

    notify.event_reminder(ntfy_user, event)

    message = ntfy.sent[0]["json"]
    assert message["title"] == "Standup"
    assert message["message"] == "Monday, March 4 at 9:00 AM – 9:30 AM\nZoom"


def test_the_digest_is_pushed(ntfy_user, ntfy):
    tasks = [
        Task.objects.create(
            user=ntfy_user, title=f"Late {n}", due_date=date(2020, 1, n)
        )
        for n in (1, 2)
    ]

    notify.past_due_digest(ntfy_user, tasks)

    message = ntfy.sent[0]["json"]
    assert message["title"] == "2 past-due tasks"
    assert "Late 1" in message["message"] and "Late 2" in message["message"]


def test_a_failed_push_goes_by_email(ntfy_user, monkeypatch, mailoutbox):
    monkeypatch.setattr(notify.requests, "post", FakeNtfy(fail=True).post)
    task = Task.objects.create(
        user=ntfy_user, title="Call the dentist", due_date=date(2030, 3, 4)
    )

    assert notify.task_reminder(ntfy_user, task)["success"]

    assert mailoutbox[0].subject.startswith("Call the dentist")


def test_a_notification_set_to_push_is_pushed_whatever_the_default(
    ntfy_user, ntfy, mailoutbox
):
    ntfy_user.notify_by = "email"
    ntfy_user.save()
    task = Task.objects.create(
        user=ntfy_user, title="Call the dentist", due_date=date(2030, 3, 4)
    )

    notify.task_reminder(ntfy_user, task, "ntfy")

    assert len(ntfy.sent) == 1 and mailoutbox == []


def test_by_email_nothing_is_pushed(user, ntfy, mailoutbox):
    task = Task.objects.create(
        user=user, title="Call the dentist", due_date=date(2030, 3, 4)
    )

    notify.task_reminder(user, task)

    assert ntfy.sent == []
    assert len(mailoutbox) == 1


# --- the Done button -----------------------------------------------------------


def _done(client, token):
    return client.post(reverse("tasks-notify-done", args=[token]))


def test_done_marks_the_task_done_without_a_login(ntfy_user):
    from django.test import Client

    task = Task.objects.create(
        user=ntfy_user, title="Call the dentist", due_date=date(2030, 3, 4)
    )
    token = notify.done_link(task).rsplit("/", 2)[-2]

    response = _done(Client(), token)

    assert response.status_code == 200
    task.refresh_from_db()
    assert task.status == 1
    assert task.completed_date == date.today()


def test_done_on_a_recurring_task_brings_the_next(ntfy_user):
    from django.test import Client

    from apps.common.recurrence import pattern_for
    from apps.tasks import recurring

    due = timezone.localdate() + timedelta(days=1)
    task = Task.objects.create(user=ntfy_user, title="Water plants", due_date=due)
    recurring.apply_edit(task, pattern_for("weekly", 1, [], due), due)
    token = notify.done_link(task).rsplit("/", 2)[-2]

    _done(Client(), token)

    following = Task.objects.get(parent_task=task.parent_task, status=0)
    assert following.due_date == due + timedelta(days=7)


def test_a_forged_link_does_nothing(ntfy_user):
    from django.test import Client

    task = Task.objects.create(user=ntfy_user, title="Call the dentist")

    response = _done(Client(), "not-a-real-token")

    assert response.status_code == 403
    task.refresh_from_db()
    assert task.status == 0


def test_pressing_done_twice_is_harmless(ntfy_user):
    from django.test import Client

    task = Task.objects.create(
        user=ntfy_user, title="Call the dentist", due_date=date(2030, 3, 4)
    )
    token = notify.done_link(task).rsplit("/", 2)[-2]

    assert _done(Client(), token).status_code == 200
    assert _done(Client(), token).status_code == 200


# --- the dev machine ---------------------------------------------------------


@pytest.fixture
def as_dev(settings):
    settings.NTFY_TOPIC_SUFFIX = "-dev"
    settings.NOTIFY_TITLE_PREFIX = "[dev] "
    settings.EMAIL_NOTIFICATIONS = False


def test_dev_pushes_to_a_channel_of_its_own_marked_as_dev(as_dev, ntfy_user, ntfy):
    task = Task.objects.create(
        user=ntfy_user, title="Call the dentist", due_date=date(2030, 3, 4)
    )

    notify.task_reminder(ntfy_user, task)

    message = ntfy.sent[0]["json"]
    assert message["topic"] == "cpl-secret-topic-dev"
    assert message["title"] == "[dev] Call the dentist"


def test_dev_sends_no_email_and_counts_it_handled(as_dev, user, ntfy, mailoutbox):
    task = Task.objects.create(
        user=user, title="Call the dentist", due_date=date(2030, 3, 4)
    )

    assert notify.task_reminder(user, task)["success"]

    assert mailoutbox == []
    assert ntfy.sent == []


def test_dev_does_not_fall_back_to_email(as_dev, ntfy_user, monkeypatch, mailoutbox):
    monkeypatch.setattr(notify.requests, "post", FakeNtfy(fail=True).post)
    task = Task.objects.create(
        user=ntfy_user, title="Call the dentist", due_date=date(2030, 3, 4)
    )

    assert not notify.task_reminder(ntfy_user, task)["success"]

    assert mailoutbox == []


def test_dev_settings_offer_the_dev_topic(as_dev, client, ntfy_user):
    page = client.get(reverse("settings-notifications")).content.decode()

    assert "ntfy://ntfy.sh/cpl-secret-topic-dev" in page
    assert "none are emailed" in page
