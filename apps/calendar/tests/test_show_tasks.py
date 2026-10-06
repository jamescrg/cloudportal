"""The calendar can show the user's open tasks beside its events."""

from datetime import date, time

import pytest
from django.urls import reverse

from apps.tasks.models import Task

pytestmark = pytest.mark.django_db

MARCH = {"start": "2030-03-01", "end": "2030-03-31"}


@pytest.fixture
def tasks(user, other_user):
    return {
        "open": Task.objects.create(user=user, title="Open", due_date=date(2030, 3, 4)),
        "timed": Task.objects.create(
            user=user, title="Timed", due_date=date(2030, 3, 5), due_time=time(14, 0)
        ),
        "done": Task.objects.create(
            user=user, title="Done", due_date=date(2030, 3, 4), status=1
        ),
        "archived": Task.objects.create(
            user=user, title="Archived", due_date=date(2030, 3, 4), archived=True
        ),
        "template": Task.objects.create(
            user=user, title="Template", due_date=date(2030, 3, 4), is_recurring=True
        ),
        "undated": Task.objects.create(user=user, title="Undated"),
        "theirs": Task.objects.create(
            user=other_user, title="Theirs", due_date=date(2030, 3, 4)
        ),
    }


def _feed(client):
    return {row["id"]: row for row in client.get(reverse("calendar:api"), MARCH).json()}


def test_tasks_are_off_by_default(client, tasks):
    assert not any(key.startswith("task-") for key in _feed(client))
    assert client.get("/calendar/").context["show_tasks"] is False


def test_the_toggle(client, tasks):
    response = client.post(reverse("calendar:show-tasks", args=["on"]))

    assert response.status_code == 204
    assert response["HX-Trigger"] == "eventsViewChanged"
    assert client.get("/calendar/").context["show_tasks"] is True
    assert "Hide tasks" in client.get("/calendar/").content.decode()

    client.post(reverse("calendar:show-tasks", args=["off"]))
    assert client.get("/calendar/").context["show_tasks"] is False
    assert (
        client.post(reverse("calendar:show-tasks", args=["maybe"])).status_code == 400
    )


def test_only_the_users_open_dated_tasks_show(client, tasks):
    client.post(reverse("calendar:show-tasks", args=["on"]))

    feed = _feed(client)
    shown = {key for key in feed if key.startswith("task-")}

    assert shown == {f"task-{tasks['open'].id}", f"task-{tasks['timed'].id}"}


def test_a_task_reads_as_a_task(client, tasks):
    client.post(reverse("calendar:show-tasks", args=["on"]))

    feed = _feed(client)
    open_task = feed[f"task-{tasks['open'].id}"]
    timed = feed[f"task-{tasks['timed'].id}"]

    assert open_task["title"] == "Open"
    assert open_task["allDay"] is True
    assert open_task["start"] == "2030-03-04"
    assert open_task["className"] == "fc-event-task"
    assert open_task["durationEditable"] is False
    assert open_task["extendedProps"] == {"kind": "task", "task_id": tasks["open"].id}
    assert timed["start"] == "2030-03-05T14:00:00-05:00"
    assert timed["allDay"] is False


def test_the_header_offers_the_toggle(client):
    html = client.get("/calendar/").content.decode()

    assert reverse("calendar:show-tasks", args=["on"]) in html
    assert "Show tasks" in html
