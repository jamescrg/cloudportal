"""GET /api/v1/sync: the full snapshot, deltas from a cursor, shared
folders seen from both sides, deletions, and cursors not honoured."""

from datetime import date, time, timedelta

import pytest
from django.utils import timezone

from apps.api import sync as sync_module
from apps.api.models import Tombstone
from apps.api.tests.conftest import by_id, settle, task_ids
from apps.folders.models import Folder
from apps.tasks import recurring
from apps.tasks.models import Task

pytestmark = pytest.mark.django_db


@pytest.fixture
def groceries(user, other_user):
    """Ollie's folder, shared with Nico."""
    folder = Folder.objects.create(user=user, page="tasks", name="Groceries")
    folder.editors.add(other_user)
    return folder


def test_a_full_snapshot(app, user, groceries):
    task = Task.objects.create(
        user=user,
        title="Renew passport",
        folder=groceries,
        priority=3,
        due_date=date(2026, 12, 1),
        due_time=time(9, 30),
        time_zone="America/New_York",
    )
    task.reminders.create(channel="ntfy", amount=30, unit="minutes")
    Task.objects.create(user=user, title="Old", archived=True)
    Task.objects.create(user=user, title="Template", is_recurring=True)
    Folder.objects.create(user=user, page="notes", name="Not a task folder")

    data = app.sync()

    assert data["full"] is True
    assert data["cursor"]
    assert data["user"] == {
        "id": user.pk,
        "name": "Ollie",
        "email": "ollie@gmail.com",
        "time_zone": "America/New_York",
        "notify_by": "email",
    }
    assert data["folder_ids"] == [groceries.pk]
    assert data["folders"] == [
        {
            "id": groceries.pk,
            "name": "Groceries",
            "mine": True,
            "shared": True,
            "shared_with": ["Nico"],
            "owner": "Ollie",
            "updated_at": data["folders"][0]["updated_at"],
        }
    ]
    assert data["deleted"] == {"tasks": [], "folders": []}
    # Archived tasks and templates are not in a snapshot
    assert task_ids(data) == {task.pk}
    sent = data["tasks"][0]
    reminder = task.reminders.get()
    assert sent == {
        "id": task.pk,
        "title": "Renew passport",
        "folder_id": groceries.pk,
        "mine": True,
        "done": False,
        "completed_date": None,
        "priority": 3,
        "archived": False,
        "due_date": "2026-12-01",
        "due_time": "09:30",
        "time_zone": "America/New_York",
        "repeat": None,
        "repeat_summary": "",
        "reminders": [
            {
                "id": reminder.pk,
                "channel": "ntfy",
                "amount": 30,
                "unit": "minutes",
                "time": None,
            }
        ],
        "created_at": sent["created_at"],
        "updated_at": sent["updated_at"],
    }
    assert sent["updated_at"].endswith("Z")


def test_due_dates_are_sent_as_stored_with_their_zone(app, user):
    Task.objects.create(
        user=user,
        title="Call London",
        due_date=date(2026, 12, 1),
        due_time=time(23, 30),
        time_zone="Europe/London",
    )

    sent = app.sync()["tasks"][0]

    assert (sent["due_date"], sent["due_time"], sent["time_zone"]) == (
        "2026-12-01",
        "23:30",
        "Europe/London",
    )


def test_an_all_day_tasks_reminder_has_its_time(app, user):
    task = Task.objects.create(user=user, title="Bins", due_date=date(2026, 12, 1))
    task.reminders.create(channel="email", amount=1, unit="days", time=time(8))

    reminder = app.sync()["tasks"][0]["reminders"][0]

    assert (reminder["amount"], reminder["unit"], reminder["time"]) == (
        1,
        "days",
        "08:00",
    )


def test_a_recurring_instance_carries_its_rule(app, user):
    task = Task.objects.create(user=user, title="Gym", due_date=date(2026, 11, 23))
    recurring.apply_edit(
        task,
        {
            "frequency": "weekly",
            "interval": 1,
            "weekdays": "0,3",
            "monthly_by": "day",
            "until": None,
            "count": None,
        },
        date(2026, 11, 23),
    )

    data = app.sync()

    assert task_ids(data) == {task.pk}
    sent = data["tasks"][0]
    assert sent["repeat"] == {
        "repeat": "weekly",
        "interval": 1,
        "weekdays": [0, 3],
        "ends": "never",
        "until": None,
        "count": None,
    }
    assert sent["repeat_summary"] == "Weekly on Monday and Thursday"


def test_a_delta_has_only_what_changed(app, user):
    kept = Task.objects.create(user=user, title="Kept")
    changed = Task.objects.create(user=user, title="Changed")
    folder = Folder.objects.create(user=user, page="tasks", name="Work")
    cursor = app.sync()["cursor"]
    settle()

    changed.title = "Changed again"
    changed.save()
    new = Task.objects.create(user=user, title="New")
    data = app.sync(cursor)

    assert data["full"] is False
    assert task_ids(data) == {changed.pk, new.pk}
    assert kept.pk not in task_ids(data)
    assert data["folders"] == []
    assert data["folder_ids"] == [folder.pk]
    assert data["cursor"] != cursor


def test_a_delta_has_archived_tasks(app, user):
    task = Task.objects.create(user=user, title="Done", status=1)
    cursor = app.sync()["cursor"]
    settle()

    task.archived = True
    task.save()
    data = app.sync(cursor)

    assert by_id(data, task.pk)["archived"] is True


def test_a_late_commit_is_not_missed(app, user):
    """A change stamped before a sync was answered but committed after it
    still comes in the next one."""
    cursor = app.sync()["cursor"]
    settle()
    task = Task.objects.create(user=user, title="Slow")
    Task.objects.filter(pk=task.pk).update(
        updated_at=timezone.now() - timedelta(minutes=2)
    )

    assert task.pk in task_ids(app.sync(cursor))


def test_deletions_come_in_a_delta(app, user):
    task = Task.objects.create(user=user, title="Going")
    folder = Folder.objects.create(user=user, page="tasks", name="Going too")
    cursor = app.sync()["cursor"]
    settle()

    ids = {"tasks": [task.pk], "folders": [folder.pk]}
    task.delete()
    folder.delete()
    data = app.sync(cursor)

    assert data["deleted"] == ids
    assert data["folder_ids"] == []


def test_another_users_deletions_are_not_told(app, other_app, other_user):
    cursor = app.sync()["cursor"]
    Task.objects.create(user=other_user, title="Theirs").delete()

    assert app.sync(cursor)["deleted"]["tasks"] == []


def test_a_cursor_not_honoured_gets_a_full_snapshot(app, user, other_app):
    Task.objects.create(user=user, title="Mine")

    assert app.sync("not-a-cursor")["full"] is True

    # Another user's
    theirs = other_app.sync()["cursor"]
    assert app.sync(theirs)["full"] is True

    # Older than the tombstones kept
    old = sync_module.make_cursor(user, timezone.now() - timedelta(days=95))
    data = app.sync(old)
    assert data["full"] is True
    assert task_ids(data)


def test_a_cursor_within_the_kept_tombstones_is_honoured(app, user):
    cursor = sync_module.make_cursor(user, timezone.now() - timedelta(days=60))
    assert app.sync(cursor)["full"] is False


# --- shared folders ----------------------------------------------------------


def test_a_shared_folder_seen_by_its_editor(other_app, user, other_user, groceries):
    ollies = Task.objects.create(user=user, title="Milk", folder=groceries)
    nicos = Task.objects.create(user=other_user, title="Eggs", folder=groceries)
    Task.objects.create(user=user, title="Ollie's own")

    data = other_app.sync()

    assert data["folder_ids"] == [groceries.pk]
    assert data["folders"][0] | {"updated_at": None} == {
        "id": groceries.pk,
        "name": "Groceries",
        "mine": False,
        "shared": True,
        "shared_with": ["Ollie"],
        "owner": "Ollie",
        "updated_at": None,
    }
    assert task_ids(data) == {ollies.pk, nicos.pk}
    assert by_id(data, ollies.pk)["mine"] is False
    assert by_id(data, nicos.pk)["mine"] is True


def test_the_owner_sees_an_editors_task(app, other_user, groceries):
    cursor = app.sync()["cursor"]
    settle()
    task = Task.objects.create(user=other_user, title="Eggs", folder=groceries)

    sent = by_id(app.sync(cursor), task.pk)

    assert sent["mine"] is False


def test_someone_given_a_folder_receives_its_tasks(other_app, user, other_user):
    folder = Folder.objects.create(user=user, page="tasks", name="Trip")
    task = Task.objects.create(user=user, title="Passports", folder=folder)
    cursor = other_app.sync()["cursor"]
    settle()

    folder.editors.add(other_user)
    data = other_app.sync(cursor)

    assert data["folder_ids"] == [folder.pk]
    assert [f["id"] for f in data["folders"]] == [folder.pk]
    assert task_ids(data) == {task.pk}


def test_the_owner_hears_a_folder_is_shared(app, user, other_user):
    folder = Folder.objects.create(user=user, page="tasks", name="Trip")
    cursor = app.sync()["cursor"]
    settle()

    folder.editors.add(other_user)
    data = app.sync(cursor)

    assert data["folders"][0]["shared_with"] == ["Nico"]


def test_someone_taken_off_a_folder_loses_it(other_app, user, other_user, groceries):
    Task.objects.create(user=user, title="Milk", folder=groceries)
    own = Task.objects.create(user=other_user, title="Eggs", folder=groceries)
    cursor = other_app.sync()["cursor"]
    settle()

    groceries.editors.remove(other_user)
    data = other_app.sync(cursor)

    assert data["folder_ids"] == []
    # Their own task in it is theirs still, in their Inbox as the site lists it
    assert task_ids(data) == {own.pk}
    assert by_id(data, own.pk)["folder_id"] is None


def test_a_task_moved_out_of_a_shared_folder_is_gone_for_the_editor(
    other_app, user, groceries
):
    task = Task.objects.create(user=user, title="Milk", folder=groceries)
    private = Folder.objects.create(user=user, page="tasks", name="Private")
    cursor = other_app.sync()["cursor"]
    settle()

    task.folder = private
    task.save()
    data = other_app.sync(cursor)

    assert task.pk not in task_ids(data)
    assert data["deleted"]["tasks"] == [task.pk]


def test_a_task_moved_back_is_not_gone(other_app, user, groceries):
    task = Task.objects.create(user=user, title="Milk", folder=groceries)
    cursor = other_app.sync()["cursor"]
    settle()

    task.folder = None
    task.save()
    task.folder = groceries
    task.save()
    data = other_app.sync(cursor)

    assert task.pk in task_ids(data)
    assert data["deleted"]["tasks"] == []


def test_a_task_deleted_in_a_shared_folder_is_gone_for_both(
    app, other_app, other_user, groceries
):
    task = Task.objects.create(user=other_user, title="Eggs", folder=groceries)
    mine = app.sync()["cursor"]
    theirs = other_app.sync()["cursor"]

    task_id = task.pk
    task.delete()

    assert app.sync(mine)["deleted"]["tasks"] == [task_id]
    assert other_app.sync(theirs)["deleted"]["tasks"] == [task_id]


def test_a_deleted_shared_folder_sends_the_editors_tasks_to_their_inbox(
    other_app, user, other_user, groceries
):
    own = Task.objects.create(user=other_user, title="Eggs", folder=groceries)
    cursor = other_app.sync()["cursor"]
    settle()

    folder_id = groceries.pk
    groceries.delete()
    data = other_app.sync(cursor)

    assert data["deleted"]["folders"] == [folder_id]
    assert by_id(data, own.pk)["folder_id"] is None


def test_a_deleted_user_leaves_tombstones(app, user, other_user, groceries):
    task = Task.objects.create(user=other_user, title="Eggs", folder=groceries)
    cursor = app.sync()["cursor"]
    settle()

    other_user.delete()
    data = app.sync(cursor)

    assert data["deleted"]["tasks"] == [task.pk]
    assert data["folders"][0]["shared_with"] == []


def test_tombstones_are_pruned_after_ninety_days(user):
    from apps.api.tracking import prune

    Task.objects.create(user=user, title="Old").delete()
    Task.objects.create(user=user, title="New").delete()
    Tombstone.objects.filter(pk=Tombstone.objects.earliest("pk").pk).update(
        deleted_at=timezone.now() - timedelta(days=91)
    )

    assert prune()["tombstones"] == 1
    assert Tombstone.objects.count() == 1


def test_the_prune_job_is_scheduled():
    from apps.management.schedules import schedule_specs

    assert "apps.api.tracking.prune" in {spec.func for spec in schedule_specs()}
