"""Every way the site, the connector and the scheduled jobs change a task,
its notifications or a task folder moves its updated_at, so the next sync
sends it; a notification marked sent does not."""

from datetime import date, time, timedelta

import pytest
from django.utils import timezone

from apps.api.models import Tombstone
from apps.api.tests.conftest import settle
from apps.common.reminders import send_due
from apps.connector import tools
from apps.folders.models import Folder
from apps.tasks.models import Task, TaskReminder

pytestmark = pytest.mark.django_db


def moved(*rows):
    """Whether each row's updated_at has moved since settle()."""
    recent = timezone.now() - timedelta(minutes=5)
    return all(type(row).objects.get(pk=row.pk).updated_at > recent for row in rows)


@pytest.fixture
def folder(user):
    return Folder.objects.create(user=user, page="tasks", name="Chores")


@pytest.fixture
def done(user, folder):
    """Two completed tasks in the folder, which the user is looking at."""
    user.tasks_folder = folder.pk
    user.save()
    return [
        Task.objects.create(user=user, title=t, folder=folder, status=1)
        for t in ("Rake", "Sweep")
    ]


def test_bulk_status(browser, done):
    settle()
    browser.get("/tasks/bulk-status?status=0")
    assert moved(*done)


def test_bulk_due_date(browser, done):
    settle()
    browser.post("/tasks/bulk-due-date", {"due_date": "tomorrow"})
    assert moved(*done)


def test_bulk_priority(browser, done):
    settle()
    browser.post("/tasks/bulk-priority/2")
    assert moved(*done)


def test_archive_completed(browser, done):
    settle()
    browser.get("/tasks/clear-htmx")
    assert moved(*done)


def test_archive_completed_by_the_older_view(browser, done):
    settle()
    browser.get("/tasks/clear")
    assert moved(*done)


def test_move_folder(browser, user, done):
    other = Folder.objects.create(user=user, page="tasks", name="Other")
    settle()
    browser.get(f"/tasks/move-folder-htmx?folder_id={other.pk}")
    assert moved(*done)


def test_moving_out_of_a_shared_folder_tells_the_editor(
    browser, user, other_user, folder, done
):
    folder.editors.add(other_user)
    browser.get("/tasks/move-folder-htmx?folder_id=")
    stones = Tombstone.objects.filter(kind="task")
    assert sorted(stones.values_list("object_id", flat=True)) == sorted(
        t.pk for t in done
    )
    assert all(stone.users == [other_user.pk] for stone in stones)


def test_due_date_and_priority_from_the_list(browser, user):
    task = Task.objects.create(user=user, title="T")
    settle()
    browser.post(f"/tasks/{task.pk}/due-date", {"due_date": "2026-12-01"})
    assert moved(task)
    settle()
    browser.get(f"/tasks/{task.pk}/priority?priority=2")
    assert moved(task)


def test_status_toggles(browser, user):
    task = Task.objects.create(user=user, title="T")
    for url in (f"/tasks/{task.pk}/status", f"/tasks/{task.pk}/done"):
        Task.objects.filter(pk=task.pk).update(status=0)
        settle()
        if url.endswith("done"):
            browser.post(url)
        else:
            browser.get(url)
        assert moved(task)


def test_reminders_added_and_removed_on_the_site(browser, user):
    task = Task.objects.create(
        user=user, title="T", due_date=date(2026, 12, 1), due_time=time(9)
    )
    settle()
    browser.post(
        f"/tasks/{task.pk}/reminders/add",
        {"amount": "30", "unit": "minutes", "channel": "email"},
    )
    reminder = task.reminders.get()
    assert moved(task)

    settle()
    browser.post(f"/tasks/{task.pk}/reminders/{reminder.pk}/delete")
    assert not task.reminders.exists()
    assert moved(task)


def test_a_reminder_marked_sent_does_not_move_its_task(user):
    now = timezone.now()
    task = Task.objects.create(
        user=user,
        title="T",
        due_date=(now + timedelta(minutes=10)).date(),
        due_time=(now + timedelta(minutes=10)).time(),
        time_zone="UTC",
    )
    TaskReminder.objects.create(task=task, channel="email", amount=30, unit="minutes")
    settle()

    sent, _ = send_due(
        TaskReminder.objects.all(), lambda *args: {"success": True}, now=now
    )

    assert sent == 1
    assert TaskReminder.objects.get().sent_for is not None
    assert not moved(task)


def test_sharing_from_the_site_moves_the_folder_and_its_tasks(
    browser, user, other_user, folder
):
    task = Task.objects.create(user=user, title="T", folder=folder)
    settle()
    browser.post(
        f"/folders/share/{folder.pk}/tasks",
        {"user_id": other_user.pk, "action": "add"},
    )
    assert folder.editors.get() == other_user
    assert moved(folder, task)

    settle()
    browser.get(f"/tasks/remove-editor/{folder.pk}/{other_user.pk}")
    assert not folder.editors.exists()
    assert moved(folder, task)


def test_renaming_a_folder_on_the_site(browser, folder):
    settle()
    browser.post(f"/folders/form/{folder.pk}/tasks", {"name": "Jobs"})
    assert moved(folder)


def test_deleting_a_folder_on_the_site(browser, user, folder):
    task = Task.objects.create(user=user, title="T", folder=folder)
    folder_id = folder.pk
    settle()
    browser.get(f"/folders/{folder_id}/tasks/delete")
    assert not Folder.objects.filter(pk=folder_id).exists()
    assert moved(task)
    assert Tombstone.objects.filter(kind="folder", object_id=folder_id).exists()


def test_leaving_a_shared_folder_on_the_site(user, other_user, folder):
    from django.test import Client

    folder.editors.add(other_user)
    settle()
    client = Client()
    client.login(username="Nico", password="clawboy")
    client.get(f"/folders/{folder.pk}/tasks/delete")
    assert Folder.objects.filter(pk=folder.pk).exists()
    assert moved(folder)


def test_deleting_completed_on_the_site_leaves_tombstones(browser, done):
    ids = sorted(t.pk for t in done)
    browser.get("/tasks/delete-completed-htmx")
    assert (
        sorted(
            Tombstone.objects.filter(kind="task").values_list("object_id", flat=True)
        )
        == ids
    )


def test_the_dialog_and_the_connector(browser, user):
    task = Task.objects.create(user=user, title="T")
    settle()
    browser.post(
        f"/tasks/{task.pk}/form",
        {"title": "Dialog", "priority": "5", "status": "0", "archived": "False"},
    )
    assert Task.objects.get(pk=task.pk).title == "Dialog"
    assert moved(task)

    settle()
    tools.update_task(user, {"task_id": task.pk, "title": "Claude"})
    assert moved(task)


def test_a_bulk_update_given_its_own_stamp_keeps_it(user):
    task = Task.objects.create(user=user, title="T")
    then = timezone.now() - timedelta(days=3)

    Task.objects.filter(pk=task.pk).update(updated_at=then)

    assert Task.objects.get(pk=task.pk).updated_at == then
