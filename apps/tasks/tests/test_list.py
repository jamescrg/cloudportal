"""The task list: priority as levels with icons, the Due column that edits
in place, and the date dropdown's presets."""

from datetime import date, timedelta

import pytest
from django.urls import reverse

from apps.tasks.models import Task
from apps.tasks.priority import level_for, levels, quick_date_filters

pytestmark = pytest.mark.django_db


# --- priority levels -------------------------------------------------------


@pytest.mark.parametrize(
    "priority, slug",
    [
        (1, "highest"),
        (2, "high"),
        (3, "high"),
        (4, "normal"),
        (6, "normal"),
        (7, "low"),
        (8, "low"),
        (9, "lowest"),
        (10, "lowest"),
    ],
)
def test_each_number_falls_in_a_level(priority, slug):
    assert level_for(priority)["slug"] == slug


def test_the_levels_in_order():
    assert [level["name"] for level in levels()] == [
        "Highest",
        "High",
        "Normal",
        "Low",
        "Lowest",
    ]


def test_the_row_shows_an_icon_for_the_level(client, user):
    Task.objects.create(user=user, title="Urgent", priority=1)

    html = client.get(reverse("tasks-list")).content.decode()

    assert 'class="priority-highest' in html
    assert "icon-chevrons-up" in html
    assert (
        reverse("tasks-priority", args=[Task.objects.get().id]) + "?priority=5" in html
    )


def test_choosing_a_level_stores_its_number(client, task):
    client.get(reverse("tasks-priority", args=[task.id]), {"priority": 8})

    task.refresh_from_db()
    assert task.priority == 8
    assert level_for(task.priority)["name"] == "Low"


# --- the Due column --------------------------------------------------------


def test_the_columns_run_check_task_due_priority(client, task):
    html = client.get(reverse("tasks-list")).content.decode()

    assert html.index('class="tasks-col-title"') < html.index('class="tasks-col-due"')
    assert html.index('class="tasks-col-due"') < html.index(
        'class="tasks-col-priority"'
    )


@pytest.fixture
def inbox_task(user):
    return Task.objects.create(user=user, title="Inbox task")


def test_setting_a_due_date_in_place(client, inbox_task):
    task = inbox_task
    response = client.post(
        reverse("tasks-due-date", args=[task.id]), {"due_date": "2030-03-04"}
    )

    assert response.status_code == 200
    assert response["HX-Trigger"] == "tasksChanged"
    task.refresh_from_db()
    assert task.due_date == date(2030, 3, 4)
    assert "2030-03-04" in response.content.decode()


def test_clearing_the_due_date_clears_the_time_too(client, task):
    task.due_date = date(2030, 3, 4)
    task.due_time = "14:00"
    task.save()

    client.post(reverse("tasks-due-date", args=[task.id]), {"due_date": ""})

    task.refresh_from_db()
    assert task.due_date is None
    assert task.due_time is None


def test_an_unreadable_due_date_is_refused(client, task):
    assert (
        client.post(
            reverse("tasks-due-date", args=[task.id]), {"due_date": "soon"}
        ).status_code
        == 400
    )
    task.refresh_from_db()
    assert task.due_date is None


def test_another_users_task_is_not_found(client):
    from accounts.models import CustomUser

    other = CustomUser.objects.create_user("Nico", "nico@gmail.com", "clawboy")
    theirs = Task.objects.create(user=other, title="Theirs")

    response = client.post(
        reverse("tasks-due-date", args=[theirs.id]), {"due_date": "2030-03-04"}
    )

    assert response.status_code == 404


def test_a_task_past_due_is_marked(client, user):
    Task.objects.create(
        user=user,
        title="Late",
        due_date=date.today() - timedelta(days=1),
    )

    assert "past-due" in client.get(reverse("tasks-list")).content.decode()


# --- the date dropdown -----------------------------------------------------


def test_the_presets_window_the_dates():
    today = date(2030, 3, 6)
    presets = quick_date_filters(today)

    assert list(presets) == [
        "all",
        "unscheduled",
        "past_due",
        "today",
        "tomorrow",
        "next7",
    ]
    assert presets["past_due"]["due_date_max"] == "2030-03-05"
    assert presets["today"]["due_date_max"] == "2030-03-06"
    assert presets["tomorrow"] == {
        "due_date_min": "2030-03-07",
        "due_date_max": "2030-03-07",
        "has_due_date": "",
    }
    assert presets["next7"]["due_date_max"] == "2030-03-12"
    assert presets["unscheduled"]["has_due_date"] == "false"


@pytest.fixture
def dated(user):
    today = date.today()
    return {
        "late": Task.objects.create(
            user=user, title="Late", due_date=today - timedelta(days=3)
        ),
        "today": Task.objects.create(user=user, title="Today", due_date=today),
        "later": Task.objects.create(
            user=user, title="Later", due_date=today + timedelta(days=30)
        ),
        "none": Task.objects.create(user=user, title="Someday"),
    }


def _titles(response):
    return sorted(t.title for t in response.context["tasks"])


def test_the_presets_filter_the_list(client, dated):
    assert _titles(client.post(reverse("tasks-filter-date", args=["past_due"]))) == [
        "Late"
    ]
    assert _titles(client.post(reverse("tasks-filter-date", args=["today"]))) == [
        "Late",
        "Today",
    ]
    assert _titles(client.post(reverse("tasks-filter-date", args=["tomorrow"]))) == []
    assert _titles(client.post(reverse("tasks-filter-date", args=["unscheduled"]))) == [
        "Someday"
    ]
    assert _titles(client.post(reverse("tasks-filter-date", args=["all"]))) == [
        "Late",
        "Later",
        "Someday",
        "Today",
    ]


def test_the_dropdown_names_the_preset_in_force(client, dated):
    response = client.post(reverse("tasks-filter-date", args=["today"]))

    assert response.context["date_filter_label"] == "today"
    assert response.context["date_filter_name"] == "Today"
    # The dropdown names the preset, and is lit while it narrows to dates
    assert (
        'class="square-button filter-button select-btn tasks-date-filter toggle-active"'
        in response.content.decode()
    )


@pytest.mark.parametrize("preset", ["all", "unscheduled"])
def test_the_dropdown_is_plain_for_all_dates_and_unscheduled(client, preset):
    response = client.post(reverse("tasks-filter-date", args=[preset]))

    assert not response.context["date_filter_scheduled"]
    assert "tasks-date-filter toggle-active" not in response.content.decode()


def test_a_preset_leaves_status_and_sort_alone(client, user, dated):
    client.post(reverse("tasks-filter"), {"status": "Pending", "sort": "title"})

    client.post(reverse("tasks-filter-date", args=["today"]))

    assert client.session["tasks_filter"]["status"] == "Pending"
    user.refresh_from_db()
    assert user.task_views == {"inbox": {"sort": "title", "date": "today"}}


def test_an_unknown_preset_is_refused(client):
    assert client.post(reverse("tasks-filter-date", args=["soon"])).status_code == 400


def test_a_preset_is_worked_out_afresh_each_day(client, dated):
    client.post(reverse("tasks-filter-date", args=["today"]))
    session = client.session
    session["tasks_filter"] = {"filter_label": "today", "due_date_max": "2000-01-01"}
    session.save()

    assert _titles(client.get(reverse("tasks-list"))) == ["Late", "Today"]


# --- archived tasks --------------------------------------------------------


def test_the_archived_dropdown_shows_and_hides_archived_tasks(client, user):
    Task.objects.create(user=user, title="Old", status=1, archived=True)
    Task.objects.create(user=user, title="Open")

    response = client.get(reverse("tasks-list"))
    assert _titles(response) == ["Open"]
    assert "Hiding archived tasks" in response.content.decode()

    response = client.post(reverse("tasks-filter-archived", args=["show"]))
    assert _titles(response) == ["Old", "Open"]
    assert "tasks-archived-filter toggle-active" in response.content.decode()
    # it is the dropdown that lights, not the Filter button
    assert not response.context["filter_active"]

    # the filter dialog leaves it as it was
    client.post(reverse("tasks-filter"), {"status": ""})
    assert _titles(client.get(reverse("tasks-list"))) == ["Old", "Open"]

    assert _titles(client.post(reverse("tasks-filter-archived", args=["hide"]))) == [
        "Open"
    ]
    assert client.post(reverse("tasks-filter-archived", args=["x"])).status_code == 400


def test_archiving_asks_first(client, user):
    Task.objects.create(user=user, title="Done", status=1)

    content = client.get(reverse("tasks-list")).content.decode()
    assert "want to archive all completed tasks?" in content


# --- each list's own view --------------------------------------------------


def _open(client, folder_id):
    return client.get(reverse("folder-select-htmx", args=[folder_id, "tasks"]))


def test_each_list_keeps_its_own_sort(client, user, folders):
    groceries, chores = folders[0], folders[1]
    for title in ["Milk", "Apples", "Eggs"]:
        Task.objects.create(user=user, folder=groceries, title=title)

    _open(client, groceries.id)
    client.get(reverse("tasks-order-by", args=["title"]))

    # another list's sort, the Inbox's, and All's don't touch it
    _open(client, chores.id)
    client.get(reverse("tasks-order-by", args=["due_date"]))
    _open(client, 0)
    client.get(reverse("tasks-order-by", args=["priority"]))
    client.get(reverse("tasks-all"))
    client.get(reverse("tasks-order-by", args=["due_date"]))

    response = _open(client, groceries.id)
    assert [t.title for t in response.context["tasks"]] == ["Apples", "Eggs", "Milk"]

    user.refresh_from_db()
    assert user.task_views == {
        str(groceries.id): {"sort": "title"},
        str(chores.id): {"sort": "due_date"},
        # Priority is the default, so one click turns it to lowest first
        "inbox": {"sort": "-priority"},
        "all": {"sort": "due_date"},
    }


def test_each_list_keeps_its_own_date_preset(client, user, folders):
    groceries, work, plain = folders[0], folders[1], folders[2]
    today = date.today()
    Task.objects.create(user=user, folder=groceries, title="Milk")
    Task.objects.create(user=user, folder=groceries, title="Party", due_date=today)
    Task.objects.create(user=user, folder=work, title="Report", due_date=today)
    Task.objects.create(user=user, folder=work, title="Someday")

    _open(client, groceries.id)
    client.post(reverse("tasks-filter-date", args=["unscheduled"]))
    _open(client, work.id)
    client.post(reverse("tasks-filter-date", args=["today"]))

    assert _titles(_open(client, groceries.id)) == ["Milk"]
    assert _titles(_open(client, work.id)) == ["Report"]
    # a list never set shows every date
    assert _open(client, plain.id).context["date_filter_label"] == "all"

    user.refresh_from_db()
    assert user.task_views == {
        str(groceries.id): {"date": "unscheduled"},
        str(work.id): {"date": "today"},
    }


def test_a_new_task_takes_the_date_of_the_list_in_view(client, user, folder):
    _open(client, folder.id)
    client.post(reverse("tasks-filter-date", args=["today"]))

    client.post(reverse("tasks-add-htmx"), {"title": "fresh", "folder_id": folder.id})

    assert Task.objects.get(title="Fresh").due_date == date.today()


def test_the_filter_dialog_sorts_the_list_in_view(client, user, folder):
    _open(client, folder.id)
    client.post(reverse("tasks-filter-date", args=["unscheduled"]))
    client.post(reverse("tasks-filter"), {"sort": "-title", "status": "Pending"})

    user.refresh_from_db()
    assert user.task_views == {
        str(folder.id): {"sort": "-title", "date": "unscheduled"}
    }
    assert "sort" not in client.session["tasks_filter"]
    assert client.get(reverse("tasks-filter")).context["sort_value"] == "-title"
    # a status alone leaves the list's date preset in force, and lights
    # the Filter button
    response = client.get(reverse("tasks-list"))
    assert response.context["date_filter_label"] == "unscheduled"
    assert response.context["filter_active"]

    # Restore Defaults puts the list back on Priority and All Dates
    client.post(reverse("tasks-filter-default"))
    user.refresh_from_db()
    assert user.task_views == {}


def test_the_dialogs_due_dates_set_the_presets_aside(client, user, dated):
    client.post(reverse("tasks-filter-date", args=["unscheduled"]))
    late = (date.today() - timedelta(days=3)).isoformat()
    client.post(reverse("tasks-filter"), {"due_date_min": late, "due_date_max": late})

    response = client.get(reverse("tasks-list"))
    assert _titles(response) == ["Late"]
    assert response.context["filter_active"]

    # choosing a preset ends them
    assert _titles(client.post(reverse("tasks-filter-date", args=["today"]))) == [
        "Late",
        "Today",
    ]


# --- bulk date and priority ------------------------------------------------


@pytest.fixture
def checked(user):
    """Two checked Inbox tasks and one unchecked; the bulk buttons act on
    the checked ones."""
    return {
        "a": Task.objects.create(user=user, title="A", status=1),
        "b": Task.objects.create(user=user, title="B", status=1),
        "open": Task.objects.create(user=user, title="Open", status=0),
    }


def test_new_tasks_start_at_normal_with_no_date_by_default(client):
    client.post(reverse("tasks-add-htmx"), {"title": "fresh"})

    task = Task.objects.get(title="Fresh")
    assert level_for(task.priority)["name"] == "Normal"
    assert task.due_date is None


@pytest.mark.parametrize(
    "preset, expected",
    [
        ("today", date.today()),
        ("tomorrow", date.today() + timedelta(days=1)),
        ("next7", None),
        ("past_due", None),
        ("unscheduled", None),
        ("all", None),
    ],
)
def test_a_new_task_takes_the_date_of_the_view_it_is_added_in(client, preset, expected):
    client.post(reverse("tasks-filter-date", args=[preset]))

    client.post(reverse("tasks-add-htmx"), {"title": "fresh"})

    assert Task.objects.get(title="Fresh").due_date == expected


def test_a_filter_pinned_to_one_day_gives_that_day(client):
    client.post(
        reverse("tasks-filter"),
        {"due_date_min": "2030-03-04", "due_date_max": "2030-03-04"},
    )

    client.post(reverse("tasks-add-htmx"), {"title": "fresh"})

    assert Task.objects.get(title="Fresh").due_date == date(2030, 3, 4)


def test_a_filter_spanning_days_gives_no_date(client):
    client.post(
        reverse("tasks-filter"),
        {"due_date_min": "2030-03-04", "due_date_max": "2030-03-08"},
    )

    client.post(reverse("tasks-add-htmx"), {"title": "fresh"})

    assert Task.objects.get(title="Fresh").due_date is None


def test_the_phone_details_carry_the_flag_and_the_date(client, user):
    Task.objects.create(
        user=user, title="Call", priority=1, due_date=date(2030, 3, 4), due_time="14:00"
    )
    Task.objects.create(user=user, title="Plain", priority=5)

    html = client.get(reverse("tasks-list")).content.decode()
    phone = [
        part for part in html.split('class="tasks-secondary tasks-secondary-phone"')[1:]
    ]

    assert "icon-chevrons-up priority-highest" in phone[0]
    assert "Mar 4" in phone[0] and "2:00 PM" in phone[0]
    assert "priority-" not in phone[1].split("</span>")[0]


def test_the_time_shows_under_the_title_and_the_date_in_its_column(client, user):
    Task.objects.create(
        user=user, title="Call", due_date=date(2030, 3, 4), due_time="14:00"
    )

    html = client.get(reverse("tasks-list")).content.decode()

    assert "2030-03-04" in html
    wide = html.split('class="tasks-secondary tasks-secondary-wide"')[1].split(
        "</span>"
    )[0]
    assert "2:00 PM" in wide
    assert "Mar 4" not in wide


@pytest.mark.parametrize(
    "value, expected",
    [
        ("today", date.today()),
        ("tomorrow", date.today() + timedelta(days=1)),
        ("week", date.today() + timedelta(days=7)),
        ("2030-03-04", date(2030, 3, 4)),
    ],
)
def test_bulk_due_date_sets_the_checked_tasks(client, checked, value, expected):
    response = client.post(reverse("tasks-bulk-due-date"), {"due_date": value})

    assert response.status_code == 200
    for key in ("a", "b"):
        checked[key].refresh_from_db()
        assert checked[key].due_date == expected
    checked["open"].refresh_from_db()
    assert checked["open"].due_date is None


def test_bulk_no_date_clears_date_and_time(client, checked):
    checked["a"].due_date = date(2030, 3, 4)
    checked["a"].due_time = "14:00"
    checked["a"].save()

    client.post(reverse("tasks-bulk-due-date"), {"due_date": ""})

    checked["a"].refresh_from_db()
    assert checked["a"].due_date is None
    assert checked["a"].due_time is None


def test_bulk_unreadable_date_is_refused(client, checked):
    assert (
        client.post(reverse("tasks-bulk-due-date"), {"due_date": "soon"}).status_code
        == 400
    )


def test_bulk_priority_sets_the_checked_tasks(client, checked):
    response = client.post(reverse("tasks-bulk-priority", args=[1]))

    assert response.status_code == 200
    for key in ("a", "b"):
        checked[key].refresh_from_db()
        assert checked[key].priority == 1
    checked["open"].refresh_from_db()
    assert checked["open"].priority == 5


def test_bulk_priority_out_of_range_is_refused(client, checked):
    assert client.post(reverse("tasks-bulk-priority", args=[11])).status_code == 400


def test_bulk_actions_stay_in_the_folder_in_view(client, user, folder, checked):
    in_folder = Task.objects.create(user=user, folder=folder, title="F", status=1)

    client.post(reverse("tasks-bulk-priority", args=[1]))

    in_folder.refresh_from_db()
    assert in_folder.priority == 5


def test_the_bulk_row_offers_date_and_priority(client, checked):
    html = client.get(reverse("tasks-list")).content.decode()

    assert reverse("tasks-bulk-due-date") in html
    assert reverse("tasks-bulk-priority", args=[5]) in html


# --- the header check is a toggle ------------------------------------------


def test_the_header_check_checks_all_then_unchecks_all(client, user):
    a = Task.objects.create(user=user, title="A")
    b = Task.objects.create(user=user, title="B", status=1)

    response = client.get(reverse("tasks-list"))
    assert response.context["all_complete"] is False
    html = response.content.decode()
    assert reverse("tasks-bulk-status") + "?status=1" in html
    assert "All Complete" not in html

    response = client.post(reverse("tasks-bulk-status") + "?status=1")
    a.refresh_from_db()
    assert a.status == 1
    assert response.context["all_complete"] is True
    assert reverse("tasks-bulk-status") + "?status=0" in response.content.decode()

    client.post(reverse("tasks-bulk-status") + "?status=0")
    a.refresh_from_db()
    b.refresh_from_db()
    assert (a.status, b.status) == (0, 0)


def test_an_empty_list_is_not_all_complete(client):
    assert client.get(reverse("tasks-list")).context["all_complete"] is False


def test_completing_keeps_the_task_in_the_list_until_archived(client, user):
    a = Task.objects.create(user=user, title="A")

    client.post(reverse("tasks-status", args=[a.id]))
    a.refresh_from_db()
    assert (a.status, a.archived) == (1, False)

    html = client.get(reverse("tasks-list")).content.decode()
    assert "text-completed" in html
    assert reverse("tasks-clear-htmx") in html

    client.post(reverse("tasks-clear-htmx"))
    a.refresh_from_db()
    assert a.archived is True
