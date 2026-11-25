"""POST /api/v1/ops: every op type, applied once each, op references,
access as on the site, and the errors."""

import json
import threading
import uuid
from datetime import date, time, timedelta

import pytest
from django.db import connection
from django.utils import timezone

from apps.api import ops as op_types
from apps.api.models import AppliedOp
from apps.api.tests.conftest import by_id, op, settle, task_ids
from apps.folders.models import Folder
from apps.tasks.models import Task

pytestmark = pytest.mark.django_db


@pytest.fixture
def groceries(user, other_user):
    folder = Folder.objects.create(user=user, page="tasks", name="Groceries")
    folder.editors.add(other_user)
    return folder


# --- the request -------------------------------------------------------------


def test_a_malformed_body_is_refused(app):
    for body in ("not json", "[]", '{"ops": {}}', '{"ops": [1]}', "{}"):
        response = app.client.post(
            "/api/v1/ops", body, content_type="application/json", **app.headers()
        )
        assert response.status_code == 400, body
        assert response.json()["error"]


def test_at_most_two_hundred_ops(app):
    response = app.post({"ops": [op("task.reopen", task=1)] * 201})

    assert response.status_code == 400


def test_an_oversized_body_is_refused(app):
    body = json.dumps({"ops": [], "padding": "x" * (op_types.MAX_OPS * 6000)})

    response = app.client.post(
        "/api/v1/ops", body, content_type="application/json", **app.headers()
    )

    assert response.status_code == 400
    assert "too large" in response.json()["error"]


def test_the_paths_answer_without_a_trailing_slash_or_redirect(app):
    """The app calls these exact paths and follows no redirects."""
    sync = app.client.get("/api/v1/sync", **app.headers())
    sent = app.post({"ops": []})

    assert sync.status_code == 200
    assert sent.status_code == 200
    assert sent.json() == {"results": []}
    for response in (sync, sent):
        assert "Location" not in response


def test_only_get_syncs_and_only_post_sends(app):
    assert app.client.post("/api/v1/sync", **app.headers()).status_code == 405
    assert app.client.get("/api/v1/ops", **app.headers()).status_code == 405


def test_an_op_without_a_uuid_is_invalid(app):
    [result] = app.send({"id": "seven", "type": "folder.create", "name": "X"})

    assert result == {
        "id": "seven",
        "ok": False,
        "error": "invalid",
        "message": "The op's id must be a UUID.",
    }
    assert not Folder.objects.exists()


def test_an_unknown_op_type_is_invalid(app):
    [result] = app.send(op("task.explode", task=1))

    assert (result["ok"], result["error"]) == (False, "invalid")


def test_a_failed_op_does_not_stop_the_rest(app, user):
    results = app.send(
        op("task.create", fields={"title": ""}),
        op("task.create", fields={"title": "Second"}),
    )

    assert [r["ok"] for r in results] == [False, True]
    assert results[0]["error"] == "invalid"
    assert Task.objects.get().title == "Second"


# --- tasks -------------------------------------------------------------------


def test_create_a_task(app, user, groceries):
    result = app.ok(
        op(
            "task.create",
            fields={
                "title": "buy milk",
                "folder_id": groceries.pk,
                "due_date": "2026-12-01",
                "due_time": "09:30",
                "time_zone": "America/New_York",
                "priority": 3,
            },
        )
    )

    task = Task.objects.get(pk=result["task_id"])
    # As the site saves it: capitalised, the user's, in their zone
    assert task.title == "Buy milk"
    assert task.user == user
    assert task.folder == groceries
    assert (task.due_date, task.due_time) == (date(2026, 12, 1), time(9, 30))
    assert task.time_zone == "America/New_York"
    assert task.priority == 3
    # The site's quick add gives a new task no notifications
    assert not task.reminders.exists()


def test_a_due_time_in_another_zone_is_kept_as_the_same_moment(app, user):
    result = app.ok(
        op(
            "task.create",
            fields={
                "title": "Call",
                "due_date": "2026-12-01",
                "due_time": "14:00",
                "time_zone": "Europe/London",
            },
        )
    )

    task = Task.objects.get(pk=result["task_id"])
    # Saved where the user is, as the site's dialog saves it
    assert (task.due_date, task.due_time, task.time_zone) == (
        date(2026, 12, 1),
        time(9),
        "America/New_York",
    )


def test_create_needs_a_title(app):
    for fields in ({}, {"title": "  "}, {"title": 5}):
        [result] = app.send(op("task.create", fields=fields))
        assert result["error"] == "invalid", fields


def test_bad_fields_are_invalid(app, user):
    task = Task.objects.create(user=user, title="T", due_date=date(2026, 12, 1))
    for fields in (
        {"priority": 11},
        {"priority": "high"},
        {"due_date": "12/01/2026"},
        {"due_time": "9:30am"},
        {"due_date": None, "due_time": "09:30"},
        {"time_zone": "Mars/Olympus"},
        {"archived": "yes"},
        {"repeat": {"repeat": "hourly"}},
        {"repeat": {"repeat": "weekly", "weekdays": [7]}},
        {"repeat": {"repeat": "daily", "ends": "after"}},
        {"colour": "red"},
        {"title": "x" * 201},
    ):
        [result] = app.send(op("task.update", task=task.pk, fields=fields))
        assert result["error"] == "invalid", fields
        assert result["message"]
    task.refresh_from_db()
    assert task.title == "T"


def test_update_changes_only_what_is_given(app, user, groceries):
    task = Task.objects.create(
        user=user,
        title="Milk",
        folder=groceries,
        priority=3,
        due_date=date(2026, 12, 1),
        due_time=time(9, 30),
    )

    app.ok(op("task.update", task=task.pk, fields={"title": "Oat milk"}))

    task.refresh_from_db()
    assert task.title == "Oat milk"
    assert task.folder == groceries
    assert task.priority == 3
    assert (task.due_date, task.due_time) == (date(2026, 12, 1), time(9, 30))


def test_update_moves_and_reprioritises_and_archives(app, user, groceries):
    task = Task.objects.create(user=user, title="Milk")

    app.ok(
        op(
            "task.update",
            task=task.pk,
            fields={"folder_id": groceries.pk, "priority": 9, "archived": True},
        )
    )
    task.refresh_from_db()
    assert (task.folder, task.priority, task.archived) == (groceries, 9, True)

    app.ok(op("task.update", task=task.pk, fields={"folder_id": None}))
    task.refresh_from_db()
    assert task.folder is None


def test_clearing_the_due_date_clears_the_time(app, user):
    task = Task.objects.create(
        user=user, title="T", due_date=date(2026, 12, 1), due_time=time(9)
    )

    app.ok(op("task.update", task=task.pk, fields={"due_date": None}))

    task.refresh_from_db()
    assert (task.due_date, task.due_time) == (None, None)


def test_a_reminder_follows_a_moved_due_date(app, user):
    task = Task.objects.create(
        user=user,
        title="T",
        due_date=date(2026, 12, 1),
        due_time=time(9),
        time_zone="America/New_York",
    )
    reminder = task.reminders.create(channel="email", amount=30, unit="minutes")
    first = reminder.fire_at

    app.ok(op("task.update", task=task.pk, fields={"due_date": "2026-12-03"}))

    reminder.refresh_from_db()
    assert reminder.fire_at == first + timedelta(days=2)


def test_complete_with_the_apps_date_and_reopen(app, user):
    task = Task.objects.create(user=user, title="T")

    app.ok(op("task.complete", task=task.pk, date="2026-11-24"))
    task.refresh_from_db()
    assert (task.status, task.completed_date) == (1, date(2026, 11, 24))

    # Completing again changes nothing
    app.ok(op("task.complete", task=task.pk, date="2026-11-25"))
    task.refresh_from_db()
    assert task.completed_date == date(2026, 11, 24)

    app.ok(op("task.reopen", task=task.pk))
    task.refresh_from_db()
    assert (task.status, task.completed_date) == (0, None)

    app.ok(op("task.reopen", task=task.pk))


def test_delete_a_task_and_again(app, user):
    task = Task.objects.create(user=user, title="T")

    app.ok(op("task.delete", task=task.pk))
    assert not Task.objects.exists()

    # Already gone is fine
    app.ok(op("task.delete", task=task.pk))
    app.ok(op("task.delete", task=f"op:{uuid.uuid4()}"))


def test_set_reminders_replaces_the_list(app, user):
    task = Task.objects.create(
        user=user, title="T", due_date=date(2026, 12, 1), due_time=time(9)
    )
    task.reminders.create(channel="email", amount=1, unit="hours")

    app.ok(
        op(
            "task.set_reminders",
            task=task.pk,
            reminders=[
                {"channel": "ntfy", "amount": 30, "unit": "minutes", "time": None},
                {"channel": "home", "amount": 1, "unit": "days", "time": None},
            ],
        )
    )

    assert sorted(task.reminders.values_list("channel", "amount", "unit")) == [
        ("home", 1, "days"),
        ("ntfy", 30, "minutes"),
    ]

    app.ok(op("task.set_reminders", task=task.pk, reminders=[]))
    assert not task.reminders.exists()


def test_an_all_day_tasks_reminders_count_in_days(app, user):
    task = Task.objects.create(user=user, title="T", due_date=date(2026, 12, 1))

    [wrong] = app.send(
        op(
            "task.set_reminders",
            task=task.pk,
            reminders=[{"channel": "email", "amount": 30, "unit": "minutes"}],
        )
    )
    assert wrong["error"] == "invalid"

    app.ok(
        op(
            "task.set_reminders",
            task=task.pk,
            reminders=[
                {"channel": "email", "amount": 1, "unit": "days", "time": "08:00"},
                {"channel": "email", "amount": 0, "unit": "days", "time": None},
            ],
        )
    )
    assert sorted(task.reminders.values_list("amount", "time")) == [
        (0, time(9)),
        (1, time(8)),
    ]


def test_reminders_need_a_due_date(app, user):
    task = Task.objects.create(user=user, title="T")

    [result] = app.send(
        op(
            "task.set_reminders",
            task=task.pk,
            reminders=[{"channel": "email", "amount": 1, "unit": "days"}],
        )
    )

    assert result["error"] == "invalid"


def test_set_reminders_moves_the_task(app, user):
    task = Task.objects.create(user=user, title="T", due_date=date(2026, 12, 1))
    cursor = app.sync()["cursor"]
    settle()

    app.ok(
        op(
            "task.set_reminders",
            task=task.pk,
            reminders=[{"channel": "email", "amount": 1, "unit": "days"}],
        )
    )

    assert by_id(app.sync(cursor), task.pk)["reminders"][0]["unit"] == "days"


def test_archive_completed_by_scope(app, user, other_user, groceries):
    inbox = Task.objects.create(user=user, title="Inbox", status=1)
    open_one = Task.objects.create(user=user, title="Open")
    in_folder = Task.objects.create(user=user, title="F", folder=groceries, status=1)
    theirs = Task.objects.create(
        user=other_user, title="Theirs", folder=groceries, status=1
    )

    app.ok(op("tasks.archive_completed", scope="inbox"))
    assert Task.objects.filter(archived=True).get() == inbox

    app.ok(op("tasks.archive_completed", scope=groceries.pk))
    assert set(Task.objects.filter(archived=True)) == {inbox, in_folder, theirs}

    open_one.status = 1
    open_one.save()
    app.ok(op("tasks.archive_completed", scope="all"))
    assert Task.objects.get(pk=open_one.pk).archived


def test_archiving_shows_in_the_next_delta(app, user):
    task = Task.objects.create(user=user, title="Done", status=1)
    cursor = app.sync()["cursor"]
    settle()

    app.ok(op("tasks.archive_completed", scope="all"))

    assert by_id(app.sync(cursor), task.pk)["archived"] is True


# --- folders -----------------------------------------------------------------


def test_create_rename_and_delete_a_folder(app, user):
    result = app.ok(op("folder.create", name="  Work  "))
    folder = Folder.objects.get(pk=result["folder_id"])
    assert (folder.name, folder.user, folder.page) == ("Work", user, "tasks")

    app.ok(op("folder.rename", folder=folder.pk, name="Office"))
    folder.refresh_from_db()
    assert folder.name == "Office"

    task = Task.objects.create(user=user, title="T", folder=folder)
    app.ok(op("folder.delete", folder=folder.pk))
    assert not Folder.objects.exists()
    # Its tasks go to the Inbox, as on the site
    task.refresh_from_db()
    assert task.folder is None

    app.ok(op("folder.delete", folder=folder.pk))


def test_folder_names_are_checked(app, user):
    for name in ("", "   ", None, "x" * 51):
        [result] = app.send(op("folder.create", name=name))
        assert result["error"] == "invalid", name


def test_an_editor_may_not_rename_and_leaves_on_delete(
    other_app, user, other_user, groceries
):
    [result] = other_app.send(op("folder.rename", folder=groceries.pk, name="Mine"))
    assert result["error"] == "forbidden"

    other_app.ok(op("folder.delete", folder=groceries.pk))

    groceries.refresh_from_db()
    assert groceries.name == "Groceries"
    assert not groceries.editors.exists()
    assert other_app.sync()["folder_ids"] == []


# --- access ------------------------------------------------------------------


def test_an_editor_acts_on_the_owners_tasks_in_a_shared_folder(
    other_app, user, other_user, groceries
):
    task = Task.objects.create(user=user, title="Milk", folder=groceries)

    other_app.ok(
        op("task.update", task=task.pk, fields={"title": "Oat milk"}),
        op("task.complete", task=task.pk, date="2026-11-25"),
    )

    task.refresh_from_db()
    assert (task.title, task.status) == ("Oat milk", 1)
    # It stays its owner's
    assert task.user == user


def test_a_task_out_of_reach_is_gone(other_app, user, other_user):
    private = Folder.objects.create(user=user, page="tasks", name="Private")
    hidden = Task.objects.create(user=user, title="Hidden", folder=private)
    template = Task.objects.create(user=other_user, title="T", is_recurring=True)

    for task_id in (hidden.pk, template.pk, 999999):
        for kind in ("task.update", "task.complete", "task.reopen"):
            [result] = other_app.send(op(kind, task=task_id, fields={"title": "x"}))
            assert result["error"] == "gone", (kind, task_id)

    [result] = other_app.send(op("task.delete", task=hidden.pk))
    assert result["ok"]
    assert Task.objects.filter(pk=hidden.pk).exists()


def test_a_folder_out_of_reach_is_gone(other_app, user):
    private = Folder.objects.create(user=user, page="tasks", name="Private")
    notes = Folder.objects.create(user=user, page="notes", name="Notes")

    for folder in (private, notes):
        results = other_app.send(
            op("task.create", fields={"title": "T", "folder_id": folder.pk}),
            op("folder.rename", folder=folder.pk, name="Mine"),
            op("tasks.archive_completed", scope=folder.pk),
        )
        assert [r["error"] for r in results] == ["gone"] * 3
    assert not Task.objects.exists()


def test_a_bad_reference_is_invalid(app):
    for task in ("12", None, True, "op:not-a-uuid"):
        [result] = app.send(op("task.complete", task=task))
        assert result["error"] == "invalid", task


# --- once only, and references -----------------------------------------------


def test_an_op_sent_again_is_answered_and_not_applied_again(app, user):
    create = op("task.create", fields={"title": "Once"})

    first = app.ok(create)
    again = app.ok(create)

    assert again == first
    assert Task.objects.count() == 1


def test_a_failed_op_sent_again_gets_the_same_answer(app, user):
    task = Task.objects.create(user=user, title="T")
    update = op("task.update", task=task.pk, fields={"priority": 0})

    [first] = app.send(update)
    [again] = app.send(update)

    assert first == again
    assert first["error"] == "invalid"


def test_op_ids_are_each_users_own(app, other_app):
    create = op("folder.create", name="Same id")

    app.ok(create)
    other_app.ok(create)

    assert Folder.objects.count() == 2


def test_references_within_a_request(app, user):
    make_folder = op("folder.create", name="Trip")
    make_task = op(
        "task.create",
        fields={"title": "Passports", "folder_id": f"op:{make_folder['id']}"},
    )

    results = app.ok(
        make_folder,
        make_task,
        op("task.complete", task=f"op:{make_task['id']}", date="2026-11-25"),
        op("folder.rename", folder=f"op:{make_folder['id']}", name="Big trip"),
    )

    task = Task.objects.get(pk=results[1]["task_id"])
    assert task.folder_id == results[0]["folder_id"]
    assert task.folder.name == "Big trip"
    assert task.status == 1


def test_references_across_requests(app, user):
    make_task = op("task.create", fields={"title": "Later"})
    app.ok(make_task)

    app.ok(op("task.update", task=f"op:{make_task['id']}", fields={"priority": 1}))

    assert Task.objects.get().priority == 1


def test_an_unknown_or_failed_reference_is_gone(app, user):
    failed = op("task.create", fields={"title": ""})
    app.send(failed)

    for ref in (f"op:{uuid.uuid4()}", f"op:{failed['id']}"):
        [result] = app.send(op("task.complete", task=ref))
        assert result["error"] == "gone"


def test_a_reference_to_another_users_op_is_gone(app, other_app):
    make_task = op("task.create", fields={"title": "Theirs"})
    other_app.ok(make_task)

    [result] = app.send(op("task.complete", task=f"op:{make_task['id']}"))

    assert result["error"] == "gone"


@pytest.mark.django_db(transaction=True)
def test_concurrent_duplicates_apply_once(user, tokens):
    """Two requests with the same op at once: one applies it, the other
    waits for it and gets its answer."""
    from apps.api.tests.conftest import App

    create = op("task.create", fields={"title": "Once"})
    answers = []

    def send():
        try:
            answers.append(App(tokens["access_token"]).send(create)[0])
        finally:
            connection.close()

    threads = [threading.Thread(target=send) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(answers) == 4
    assert all(answer == answers[0] for answer in answers)
    assert Task.objects.count() == 1
    assert AppliedOp.objects.count() == 1


def test_applied_ops_are_pruned_with_tombstones(app, user):
    from apps.api.tracking import prune

    app.ok(op("folder.create", name="Old"))
    AppliedOp.objects.update(created_at=timezone.now() - timedelta(days=91))

    assert prune()["ops"] == 1


def test_a_full_round_trip(app, user):
    data = app.sync()
    make_task = op("task.create", fields={"title": "From the phone"})
    result = app.ok(make_task)

    delta = app.sync(data["cursor"])

    assert result["task_id"] in task_ids(delta)
