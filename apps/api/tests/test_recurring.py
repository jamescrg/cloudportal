"""Recurring tasks through the API behave as from the site's dialog: a
repeat makes a template, completing brings on the next instance, an edit
passes to the template, and taking the repeat off removes it."""

from datetime import date, timedelta

import pytest
from django.utils import timezone

from apps.api.tests.conftest import by_id, op, settle, task_ids
from apps.tasks import recurring
from apps.tasks.models import Task

pytestmark = pytest.mark.django_db

WEEKLY = {
    "repeat": "weekly",
    "interval": 1,
    "weekdays": [0, 3],
    "ends": "never",
    "until": None,
    "count": None,
}


def _upcoming(weekday):
    today = timezone.localdate()
    return today + timedelta(days=(weekday - today.weekday()) % 7 or 7)


@pytest.fixture
def gym(app, user):
    """A weekly task made in the app, due next Monday."""
    result = app.ok(
        op(
            "task.create",
            fields={
                "title": "Gym",
                "due_date": _upcoming(0).isoformat(),
                "priority": 3,
                "repeat": WEEKLY,
            },
        )
    )
    return Task.objects.get(pk=result["task_id"])


def test_a_repeat_makes_a_template(app, gym):
    template = gym.parent_task

    assert template.is_recurring
    assert template.title == "Gym"
    assert template.repeat_frequency == "weekly"
    assert template.repeat_weekdays == "0,3"

    data = app.sync()
    # The template is never sent
    assert task_ids(data) == {gym.pk}
    sent = by_id(data, gym.pk)
    assert sent["repeat"] == WEEKLY
    assert sent["repeat_summary"] == "Weekly on Monday and Thursday"


def test_completing_brings_on_the_next_instance(app, gym):
    cursor = app.sync()["cursor"]
    settle()

    app.ok(op("task.complete", task=gym.pk, date=timezone.localdate().isoformat()))
    data = app.sync(cursor)

    upcoming = Task.objects.get(parent_task=gym.parent_task, status=0)
    assert task_ids(data) == {gym.pk, upcoming.pk}
    assert by_id(data, gym.pk)["done"] is True
    sent = by_id(data, upcoming.pk)
    assert sent["due_date"] == (_upcoming(0) + timedelta(days=3)).isoformat()
    assert sent["repeat"] == WEEKLY
    assert sent["title"] == "Gym"


def test_editing_an_instance_passes_to_the_template(app, gym):
    app.ok(
        op(
            "task.update",
            task=gym.pk,
            fields={
                "title": "Swim",
                "priority": 1,
                "repeat": WEEKLY | {"weekdays": [2]},
            },
        )
    )

    template = Task.objects.get(pk=gym.parent_task_id)
    assert (template.title, template.priority) == ("Swim", 1)
    assert template.repeat_weekdays == "2"
    assert by_id(app.sync(), gym.pk)["repeat_summary"] == "Weekly on Wednesday"


def test_a_changed_rule_reaches_the_earlier_instances(app, gym):
    app.ok(op("task.complete", task=gym.pk, date=timezone.localdate().isoformat()))
    upcoming = Task.objects.get(parent_task=gym.parent_task, status=0)
    cursor = app.sync()["cursor"]
    settle()

    app.ok(
        op(
            "task.update",
            task=upcoming.pk,
            fields={"repeat": WEEKLY | {"repeat": "daily", "weekdays": []}},
        )
    )
    data = app.sync(cursor)

    # The one done earlier shows the new rule too
    assert by_id(data, gym.pk)["repeat_summary"] == "Daily"


def test_taking_the_repeat_off_removes_the_template(app, gym):
    template_id = gym.parent_task_id
    cursor = app.sync()["cursor"]
    settle()

    app.ok(op("task.update", task=gym.pk, fields={"repeat": None}))

    assert not Task.objects.filter(pk=template_id).exists()
    gym.refresh_from_db()
    assert gym.parent_task is None
    data = app.sync(cursor)
    assert by_id(data, gym.pk)["repeat"] is None
    # The template was never sent, so it is not told as deleted
    assert data["deleted"]["tasks"] == []


def test_a_repeat_ending_after_a_count(app, user):
    result = app.ok(
        op(
            "task.create",
            fields={
                "title": "Pills",
                "due_date": timezone.localdate().isoformat(),
                "repeat": {"repeat": "daily", "ends": "after", "count": 5},
            },
        )
    )

    sent = by_id(app.sync(), result["task_id"])
    assert (sent["repeat"]["ends"], sent["repeat"]["count"]) == ("after", 5)
    assert sent["repeat_summary"] == "Daily, 5 times"


def test_reminders_set_on_an_instance_reach_the_template(app, gym):
    app.ok(
        op(
            "task.set_reminders",
            task=gym.pk,
            reminders=[{"channel": "ntfy", "amount": 1, "unit": "days"}],
        )
    )

    template = Task.objects.get(pk=gym.parent_task_id)
    assert list(template.reminders.values_list("channel", "unit")) == [("ntfy", "days")]

    app.ok(op("task.complete", task=gym.pk, date=timezone.localdate().isoformat()))
    upcoming = Task.objects.get(parent_task=template, status=0)
    assert by_id(app.sync(), upcoming.pk)["reminders"][0]["channel"] == "ntfy"


def test_a_stale_instance_removed_by_the_daily_job_is_told(app, gym):
    extra = Task.objects.create(
        user=gym.user,
        title="Gym",
        parent_task=gym.parent_task,
        due_date=gym.due_date - timedelta(days=7),
    )
    cursor = app.sync()["cursor"]
    settle()

    recurring.create_instances()

    assert app.sync(cursor)["deleted"]["tasks"] == [extra.pk]


def test_the_daily_job_makes_an_instance_that_comes_in_a_delta(app, user):
    template = Task.objects.create(
        user=user, title="Water plants", is_recurring=True, status=0
    )
    template.set_rule(
        {
            "frequency": "daily",
            "interval": 1,
            "weekdays": "",
            "monthly_by": "day",
            "until": None,
            "count": None,
        },
        date.today(),
    )
    template.save()
    cursor = app.sync()["cursor"]
    settle()

    assert recurring.create_instances() == 1

    made = Task.objects.get(parent_task=template)
    assert task_ids(app.sync(cursor)) == {made.pk}
