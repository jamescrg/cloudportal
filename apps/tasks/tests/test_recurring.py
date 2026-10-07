"""Recurring tasks: a hidden template with the rule repeating events use,
and one open instance at a time, the next due on the rule's next day."""

from datetime import date, time, timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.tasks import recurring
from apps.tasks.models import Task, TaskReminder

pytestmark = pytest.mark.django_db


def _today():
    return timezone.localdate()


def _form_data(task, **changes):
    data = {
        "title": task.title,
        "due_date": str(task.due_date) if task.due_date else "",
        "due_time": "",
        "priority": 5,
        "status": task.status,
        "archived": "False",
        "folder": "",
    }
    return data | changes


def _recurring(client, user, due=None, **repeat):
    """A task made recurring through its form; returns (instance, template)."""
    task = Task.objects.create(
        user=user, title="Water plants", due_date=due or _today()
    )
    client.post(
        reverse("tasks-form", args=[task.id]),
        _form_data(task, **({"repeat": "weekly", "interval": 1} | repeat)),
    )
    task.refresh_from_db()
    return task, task.parent_task


# --- making a task recur ---------------------------------------------------


def test_a_task_given_a_repeat_becomes_the_first_instance_of_a_template(client, user):
    due = _today() + timedelta(days=2)

    task, template = _recurring(client, user, due=due)

    assert template.is_recurring
    assert template.rule.frequency == "weekly"
    assert template.repeat_weekdays == str(due.weekday())
    assert template.repeat_start == due
    assert template.title == "Water plants"
    # The task keeps its own day; the template is hidden from the list
    assert task.due_date == due
    assert task.status == 0
    page = client.get(reverse("tasks")).content.decode()
    assert page.count("Water plants") == 1


def test_the_template_takes_the_tasks_notifications(client, user):
    task = Task.objects.create(user=user, title="Water plants", due_date=_today())
    TaskReminder.objects.create(task=task, amount=1, unit="days", time=time(9, 0))

    client.post(
        reverse("tasks-form", args=[task.id]),
        _form_data(task, repeat="daily", interval=1),
    )

    task.refresh_from_db()
    assert task.parent_task.reminders.get().describe() == "1 day before at 9:00 AM"


# --- completing an instance ------------------------------------------------


def test_completing_an_instance_brings_the_next_on_the_rules_next_day(client, user):
    due = _today() + timedelta(days=1)
    task, template = _recurring(client, user, due=due)

    client.get(reverse("tasks-status", args=[task.id]))

    following = Task.objects.get(parent_task=template, status=0)
    assert following.due_date == due + timedelta(days=7)
    assert following.title == "Water plants"


def test_the_next_instance_is_never_due_in_the_past(client, user):
    long_ago = _today() - timedelta(days=30)
    task, template = _recurring(client, user, due=long_ago, repeat="daily")

    client.get(reverse("tasks-status", args=[task.id]))

    following = Task.objects.get(parent_task=template, status=0)
    assert following.due_date == _today()


def test_every_other_week_on_two_days(client, user):
    # A Monday, repeating every two weeks on Monday and Thursday
    monday = _today() + timedelta(days=(7 - _today().weekday()) % 7 or 7)
    task, template = _recurring(
        client, user, due=monday, interval=2, weekdays=["0", "3"]
    )

    days = []
    current = task
    for _ in range(3):
        client.get(reverse("tasks-status", args=[current.id]))
        current = Task.objects.get(parent_task=template, status=0)
        days.append(current.due_date)

    assert days == [
        monday + timedelta(days=3),
        monday + timedelta(days=14),
        monday + timedelta(days=17),
    ]


def test_marking_done_in_the_form_brings_the_next_too(client, user):
    task, template = _recurring(client, user, repeat="daily")

    client.post(
        reverse("tasks-form", args=[task.id]),
        _form_data(task, status=1, repeat="daily", interval=1),
    )

    assert Task.objects.filter(parent_task=template, status=0).count() == 1


def test_a_rule_that_has_ended_brings_no_more(client, user):
    task, template = _recurring(client, user, repeat="daily", ends="after", count=1)

    client.get(reverse("tasks-status", args=[task.id]))

    assert not Task.objects.filter(parent_task=template, status=0).exists()


# --- editing ---------------------------------------------------------------


def test_an_instances_edit_reaches_its_template(client, user):
    task, template = _recurring(client, user)

    client.post(
        reverse("tasks-form", args=[task.id]),
        _form_data(task, title="Water the plants", repeat="monthly", interval=1),
    )

    template.refresh_from_db()
    assert template.title == "Water the plants"
    assert template.rule.frequency == "monthly"
    assert template.repeat_start == task.due_date


def test_removing_the_repeat_leaves_the_task_alone(client, user):
    task, template = _recurring(client, user)

    client.post(reverse("tasks-form", args=[task.id]), _form_data(task, repeat=""))

    task.refresh_from_db()
    assert task.parent_task is None
    assert not Task.objects.filter(pk=template.pk).exists()


def test_the_form_opens_on_the_rule(client, user):
    task, template = _recurring(client, user, interval=3)

    page = client.get(reverse("tasks-form", args=[task.id]))

    form = page.context["form"]
    assert form["repeat"].value() == "weekly"
    assert form["interval"].value() == 3
    assert "Every 3 weeks on" in page.content.decode()


# --- the daily job ---------------------------------------------------------


def _template(user, **rule):
    fields = {
        "repeat_frequency": "daily",
        "repeat_start": _today() - timedelta(days=10),
    } | rule
    return Task.objects.create(user=user, title="Stretch", is_recurring=True, **fields)


def test_the_job_gives_a_template_without_an_open_instance_its_next(user):
    template = _template(user, repeat_frequency="weekly", repeat_weekdays="2")

    assert recurring.create_instances() == 1

    instance = Task.objects.get(parent_task=template)
    assert instance.due_date.weekday() == 2
    assert _today() <= instance.due_date < _today() + timedelta(days=7)
    assert recurring.create_instances() == 0


def test_the_job_follows_on_from_the_last_instance(user):
    template = _template(user, repeat_frequency="daily")
    tomorrow = _today() + timedelta(days=1)
    Task.objects.create(
        user=user, title="Stretch", parent_task=template, status=1, due_date=tomorrow
    )

    recurring.create_instances()

    assert Task.objects.get(
        parent_task=template, status=0
    ).due_date == tomorrow + timedelta(days=1)


def test_the_job_leaves_one_open_instance(user):
    template = _template(user)
    for days in (1, 2, 3):
        Task.objects.create(
            user=user,
            title="Stretch",
            parent_task=template,
            due_date=_today() + timedelta(days=days),
        )

    recurring.create_instances()

    open_ones = Task.objects.filter(parent_task=template, status=0)
    assert list(open_ones.values_list("due_date", flat=True)) == [
        _today() + timedelta(days=3)
    ]


def test_the_job_skips_an_ended_rule(user):
    _template(user, repeat_until=_today() - timedelta(days=1))

    assert recurring.create_instances() == 0


# --- the old rules, converted ----------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_old_rules_convert_to_the_same_days():
    from django.contrib.auth import get_user_model
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor

    before = [("tasks", "0017_task_priority_default")]
    owner = get_user_model().objects.create_user("convert", "convert@example.com", "x")
    executor = MigrationExecutor(connection)
    executor.migrate(before)
    try:
        OldTask = executor.loader.project_state(before).apps.get_model("tasks", "Task")
        made = {
            name: OldTask.objects.create(
                user_id=owner.pk,
                title=name,
                is_recurring=True,
                due_date=date(2025, 12, 1),
                **fields,
            ).pk
            for name, fields in {
                "daily": {"recurrence_type": "daily"},
                "weekly": {"recurrence_type": "weekly", "recurrence_day": 4},
                "monthly": {"recurrence_type": "monthly", "recurrence_day": 8},
                "yearly": {
                    "recurrence_type": "yearly",
                    "recurrence_day": 29,
                    "recurrence_month": 2,
                },
            }.items()
        }
    finally:
        # Whatever happened, the schema goes forward again for the tests after
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())

    converted = {name: Task.objects.get(pk=pk) for name, pk in made.items()}
    assert converted["daily"].repeat_summary == "Daily"
    assert converted["daily"].repeat_start == date(2025, 12, 1)
    assert converted["weekly"].repeat_summary == "Weekly on Friday"
    assert converted["weekly"].repeat_start == date(2025, 12, 5)
    assert converted["monthly"].repeat_summary == "Monthly on day 8"
    assert converted["monthly"].repeat_start == date(2025, 12, 8)
    assert converted["yearly"].repeat_summary == "Annually on February 29"
    assert converted["yearly"].repeat_start == date(2028, 2, 29)
