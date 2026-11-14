"""The connector's tools change the user's tasks and calendar as the site's
own dialogs do, and reach nothing of anyone else's."""

from datetime import date, time, timedelta

import pytest

from apps.calendar import recurrence
from apps.calendar.models import Event
from apps.common.recurrence import pattern_for
from apps.folders.models import Folder
from apps.tasks import recurring
from apps.tasks.models import Task

pytestmark = pytest.mark.django_db


@pytest.fixture
def chores(user):
    return Folder.objects.create(user=user, page="tasks", name="Chores")


# --- tasks -------------------------------------------------------------------


def test_folders_are_listed_with_their_ids(claude, chores):
    result = claude.ok("list_task_folders")

    assert result["folders"] == [{"id": chores.id, "name": "Chores"}]


def test_a_task_is_added_as_from_the_dialog(claude, user, chores):
    created = claude.ok(
        "create_task",
        title="buy milk",
        folder_id=chores.id,
        due_date="2030-03-06",
        due_time="17:30",
        priority="High",
    )["created"]

    task = Task.objects.get(pk=created["id"])
    assert task.user == user
    assert task.title == "Buy milk"
    assert task.folder == chores
    assert task.due_date == date(2030, 3, 6)
    assert task.due_time == time(17, 30)
    assert task.time_zone == "America/New_York"
    assert created["priority"] == "High"
    assert created["folder"] == "Chores"


def test_a_task_needs_a_title(claude):
    assert "title" in claude.fails("create_task", title="  ")


def test_a_bad_priority_is_explained(claude):
    assert "Highest, High, Normal, Low, Lowest" in claude.fails(
        "create_task", title="Thing", priority="urgent"
    )


def test_another_users_folder_is_not_offered(claude, other_user):
    theirs = Folder.objects.create(user=other_user, page="tasks", name="Theirs")

    assert "no task folder" in claude.fails(
        "create_task", title="Sneak", folder_id=theirs.id
    )


def test_find_tasks_filters_by_status_folder_dates_and_text(claude, user, chores):
    Task.objects.create(user=user, title="Wash car", due_date=date(2030, 3, 1))
    Task.objects.create(user=user, title="Wash dog", folder=chores)
    Task.objects.create(user=user, title="Done one", status=1)
    Task.objects.create(user=user, title="Old", archived=True)

    def titles(**args):
        return [t["title"] for t in claude.ok("find_tasks", **args)["tasks"]]

    assert titles() == ["Wash car", "Wash dog"]
    assert titles(status="done") == ["Done one"]
    assert titles(folder_id=chores.id) == ["Wash dog"]
    assert titles(folder_id=None) == ["Wash car"]
    assert titles(due_to="2030-03-02") == ["Wash car"]
    assert titles(text="dog") == ["Wash dog"]
    assert "Old" in titles(status="all", include_archived=True)


def test_find_tasks_says_how_many_there_are_past_the_limit(claude, user):
    for n in range(5):
        Task.objects.create(user=user, title=f"Task {n}")

    result = claude.ok("find_tasks", limit=2)

    assert result["shown"] == 2
    assert result["total"] == 5


def test_a_task_changes_only_where_asked(claude, user, chores):
    task = Task.objects.create(
        user=user,
        title="Pay rent",
        folder=chores,
        due_date=date(2030, 3, 1),
        due_time=time(9, 0),
        priority=3,
    )

    claude.ok("update_task", task_id=task.id, title="pay the rent")

    task.refresh_from_db()
    assert task.title == "Pay the rent"
    assert task.folder == chores
    assert task.due_date == date(2030, 3, 1)
    assert task.due_time == time(9, 0)
    assert task.priority == 3


def test_a_tasks_date_can_be_taken_off(claude, user):
    task = Task.objects.create(
        user=user, title="Someday", due_date=date(2030, 3, 1), due_time=time(9, 0)
    )

    claude.ok("update_task", task_id=task.id, due_date=None)

    task.refresh_from_db()
    assert task.due_date is None
    assert task.due_time is None


def test_a_task_moves_to_the_inbox(claude, user, chores):
    task = Task.objects.create(user=user, title="Loose", folder=chores)

    claude.ok("update_task", task_id=task.id, folder_id=None)

    task.refresh_from_db()
    assert task.folder is None


def test_another_users_task_cannot_be_touched(claude, other_user):
    theirs = Task.objects.create(user=other_user, title="Private")

    assert "no task" in claude.fails("update_task", task_id=theirs.id, title="Mine")
    assert "no task" in claude.fails("complete_task", task_id=theirs.id)
    assert claude.ok("find_tasks")["tasks"] == []


def test_completing_a_task_marks_it_done_today(claude, user):
    task = Task.objects.create(user=user, title="Call mum")

    result = claude.ok("complete_task", task_id=task.id)

    task.refresh_from_db()
    assert task.status == 1
    assert task.completed_date == date.today()
    assert result["completed"]["done"] is True
    assert claude.ok("complete_task", task_id=task.id)["note"]


def test_completing_a_repeating_task_brings_on_the_next(claude, user):
    task = Task.objects.create(user=user, title="Water plants", due_date=date.today())
    recurring.apply_edit(task, pattern_for("daily", 1, [], date.today()), date.today())

    result = claude.ok("complete_task", task_id=task.id)

    assert result["next"]["title"] == "Water plants"
    assert result["next"]["due_date"] == (date.today() + timedelta(days=1)).isoformat()


def test_editing_a_repeating_task_keeps_it_repeating(claude, user):
    task = Task.objects.create(user=user, title="Water plants", due_date=date.today())
    recurring.apply_edit(task, pattern_for("daily", 1, [], date.today()), date.today())

    claude.ok("update_task", task_id=task.id, title="Water the plants")

    task.refresh_from_db()
    assert task.parent_task is not None
    assert task.parent_task.title == "Water the plants"
    assert task.parent_task.rule is not None


def test_a_done_task_reopens(claude, user):
    task = Task.objects.create(
        user=user, title="Oops", status=1, completed_date=date.today()
    )

    claude.ok("reopen_task", task_id=task.id)

    task.refresh_from_db()
    assert task.status == 0
    assert task.completed_date is None


# --- calendar ----------------------------------------------------------------


def test_an_event_is_added_as_from_the_dialog(claude, user):
    created = claude.ok(
        "create_event",
        title="Dentist",
        date="2030-03-06",
        start_time="14:00",
        location="Main St",
    )["created"]

    event = Event.objects.get(pk=created["id"])
    assert event.user == user
    assert event.description == "Dentist"
    assert event.start_time == time(14, 0)
    # a start and no end runs an hour
    assert event.end_time == time(15, 0)
    assert event.time_zone == "America/New_York"
    assert created["all_day"] is False


def test_an_event_without_a_time_is_all_day(claude):
    created = claude.ok("create_event", title="Holiday", date="2030-03-06")["created"]

    assert created["all_day"] is True
    assert created["start_time"] is None


def test_an_events_errors_come_back_from_its_form(claude):
    message = claude.fails(
        "create_event", title="Trip", date="2030-03-06", end_date="2030-03-01"
    )

    assert "End date must be after the date." in message
    assert "4 or more" in claude.fails("create_event", title="Hi", date="2030-03-06")


def test_events_are_listed_between_two_days(claude, user, other_user):
    Event.objects.create(user=user, date=date(2030, 3, 6), description="In range")
    Event.objects.create(user=user, date=date(2030, 4, 6), description="Later")
    Event.objects.create(
        user=user,
        date=date(2030, 3, 1),
        end_date=date(2030, 3, 7),
        description="Across",
    )
    Event.objects.create(user=other_user, date=date(2030, 3, 6), description="Theirs")

    result = claude.ok("list_events", start="2030-03-05", end="2030-03-10")

    assert [e["title"] for e in result["events"]] == ["Across", "In range"]


def test_an_event_changes_only_where_asked(claude, user):
    event = Event.objects.create(
        user=user,
        date=date(2030, 3, 6),
        start_time=time(9, 0),
        end_time=time(10, 0),
        description="Standup",
        location="Office",
        time_zone="America/New_York",
    )

    claude.ok("update_event", event_id=event.id, start_time="09:30", end_time="10:30")

    event.refresh_from_db()
    assert event.start_time == time(9, 30)
    assert event.end_time == time(10, 30)
    assert event.description == "Standup"
    assert event.location == "Office"
    assert event.date == date(2030, 3, 6)


def test_an_event_made_all_day_loses_its_times(claude, user):
    event = Event.objects.create(
        user=user,
        date=date(2030, 3, 6),
        start_time=time(9, 0),
        end_time=time(10, 0),
        description="Standup",
    )

    claude.ok("update_event", event_id=event.id, start_time=None)

    event.refresh_from_db()
    assert event.start_time is None
    assert event.end_time is None


def test_one_occurrence_of_a_repeating_event_changes_alone(claude, user):
    first = Event.objects.create(
        user=user, date=date(2030, 3, 4), description="Weekly review"
    )
    recurrence.start_series(
        first, pattern_for("weekly", 1, ["0"], date(2030, 3, 4)), today=date(2030, 3, 1)
    )
    occurrences = list(first.series.occurrences.order_by("date")[:3])

    claude.ok("update_event", event_id=occurrences[1].id, title="Monthly review")

    titles = [e.description for e in first.series.occurrences.order_by("date")[:3]]
    assert titles == ["Weekly review", "Monthly review", "Weekly review"]
    assert Event.objects.get(pk=occurrences[1].id).series_id == first.series_id


def test_another_users_event_cannot_be_touched(claude, other_user):
    theirs = Event.objects.create(
        user=other_user, date=date(2030, 3, 6), description="Private"
    )

    assert "no event" in claude.fails(
        "update_event", event_id=theirs.id, title="Mine now"
    )
