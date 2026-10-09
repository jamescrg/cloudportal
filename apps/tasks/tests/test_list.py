"""The task list: priority as levels with icons, the Due column that edits
in place, and the date dropdown's presets."""

from datetime import date, time, timedelta

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
    # The dropdown names the preset; it is not lit in the accent colour
    assert (
        'class="square-button filter-button select-btn tasks-date-filter"'
        in response.content.decode()
    )


def test_a_preset_leaves_status_and_sort_alone(client, dated):
    client.post(reverse("tasks-filter"), {"status": "Pending", "sort": "title"})

    client.post(reverse("tasks-filter-date", args=["today"]))

    saved = client.session["tasks_filter"]
    assert saved["status"] == "Pending"
    assert saved["sort"] == "title"
    assert saved["filter_label"] == "today"


def test_an_unknown_preset_is_refused(client):
    assert client.post(reverse("tasks-filter-date", args=["soon"])).status_code == 400


def test_a_preset_is_worked_out_afresh_each_day(client, dated):
    client.post(reverse("tasks-filter-date", args=["today"]))
    stale = client.session["tasks_filter"]
    stale["due_date_max"] = "2000-01-01"
    session = client.session
    session["tasks_filter"] = stale
    session.save()

    assert _titles(client.get(reverse("tasks-list"))) == ["Late", "Today"]


# --- bulk actions on the selection ------------------------------------------


@pytest.fixture
def selected(user):
    """Three Inbox tasks; a bulk action is sent the ids of the ones picked
    (a and b here) and leaves the rest alone."""
    return {
        "a": Task.objects.create(user=user, title="A"),
        "b": Task.objects.create(user=user, title="B"),
        "other": Task.objects.create(user=user, title="Other"),
    }


def _ids(*tasks):
    return ",".join(str(task.id) for task in tasks)


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
def test_bulk_due_date_sets_the_selected_tasks(client, selected, value, expected):
    response = client.post(
        reverse("tasks-bulk-due-date"),
        {"due_date": value, "ids": _ids(selected["a"], selected["b"])},
    )

    assert response.status_code == 200
    for key in ("a", "b"):
        selected[key].refresh_from_db()
        assert selected[key].due_date == expected
    selected["other"].refresh_from_db()
    assert selected["other"].due_date is None


def test_bulk_no_date_clears_date_and_time(client, selected):
    selected["a"].due_date = date(2030, 3, 4)
    selected["a"].due_time = time(9, 0)
    selected["a"].save()

    client.post(
        reverse("tasks-bulk-due-date"), {"due_date": "", "ids": _ids(selected["a"])}
    )

    selected["a"].refresh_from_db()
    assert (selected["a"].due_date, selected["a"].due_time) == (None, None)


def test_bulk_unreadable_date_is_refused(client, selected):
    response = client.post(
        reverse("tasks-bulk-due-date"), {"due_date": "soon", "ids": _ids(selected["a"])}
    )
    assert response.status_code == 400


def test_bulk_priority_sets_the_selected_tasks(client, selected):
    response = client.post(
        reverse("tasks-bulk-priority", args=[1]),
        {"ids": _ids(selected["a"], selected["b"])},
    )

    assert response.status_code == 200
    for key in ("a", "b"):
        selected[key].refresh_from_db()
        assert selected[key].priority == 1
    selected["other"].refresh_from_db()
    assert selected["other"].priority == 5


def test_bulk_priority_out_of_range_is_refused(client, selected):
    response = client.post(
        reverse("tasks-bulk-priority", args=[11]), {"ids": _ids(selected["a"])}
    )
    assert response.status_code == 400


def test_bulk_actions_reach_only_the_tasks_sent(client, user, selected):
    from accounts.models import CustomUser

    other = CustomUser.objects.create_user("Nico", "nico@gmail.com", "clawboy")
    theirs = Task.objects.create(user=other, title="Theirs")

    client.post(
        reverse("tasks-bulk-priority", args=[1]), {"ids": _ids(selected["a"], theirs)}
    )
    client.post(reverse("tasks-bulk-priority", args=[2]))

    selected["a"].refresh_from_db()
    theirs.refresh_from_db()
    selected["b"].refresh_from_db()
    assert (selected["a"].priority, theirs.priority, selected["b"].priority) == (
        1,
        5,
        5,
    )


def test_bulk_move_puts_the_selected_tasks_in_a_folder_or_the_inbox(
    client, user, folder, selected
):
    client.post(
        reverse("tasks-move-folder-htmx") + f"?folder_id={folder.id}",
        {"ids": _ids(selected["a"])},
    )
    selected["a"].refresh_from_db()
    selected["b"].refresh_from_db()
    assert (selected["a"].folder, selected["b"].folder) == (folder, None)

    client.post(
        reverse("tasks-move-folder-htmx") + "?folder_id=", {"ids": _ids(selected["a"])}
    )
    selected["a"].refresh_from_db()
    assert selected["a"].folder is None


def test_bulk_status_marks_the_selected_complete_or_pending(client, user, selected):
    client.post(
        reverse("tasks-bulk-status") + "?status=1",
        {"ids": _ids(selected["a"], selected["b"])},
    )
    for key in ("a", "b", "other"):
        selected[key].refresh_from_db()
    assert (selected["a"].status, selected["b"].status, selected["other"].status) == (
        1,
        1,
        0,
    )
    assert selected["a"].completed_date == date.today()

    client.post(
        reverse("tasks-bulk-status") + "?status=0", {"ids": _ids(selected["a"])}
    )
    selected["a"].refresh_from_db()
    selected["b"].refresh_from_db()
    assert (
        selected["a"].status,
        selected["a"].completed_date,
        selected["b"].status,
    ) == (0, None, 1)


def test_bulk_complete_follows_the_completion_mode(client, user, selected):
    user.task_completion_mode = "delete"
    user.save()

    client.post(
        reverse("tasks-bulk-status") + "?status=1", {"ids": _ids(selected["a"])}
    )

    assert not Task.objects.filter(pk=selected["a"].pk).exists()
    assert Task.objects.filter(pk=selected["b"].pk).exists()


def test_the_list_offers_selecting_and_the_bulk_actions(client, selected):
    html = client.get(reverse("tasks-list")).content.decode()

    assert "tasks-select-toggle" in html
    assert f'data-task-id="{selected["a"].id}"' in html
    assert f'pick({selected["a"].id})' in html
    assert reverse("tasks-bulk-due-date") in html
    assert reverse("tasks-bulk-priority", args=[5]) in html
    assert reverse("tasks-bulk-status") + "?status=1" in html
    assert "Done" in html


def test_the_header_circle_completes_all_then_sets_all_pending(client, user):
    a = Task.objects.create(user=user, title="A")
    b = Task.objects.create(user=user, title="B", status=1)

    response = client.get(reverse("tasks-list"))
    assert response.context["all_complete"] is False
    assert reverse("tasks-bulk-status") + "?all=1&status=1" in response.content.decode()

    response = client.post(reverse("tasks-bulk-status") + "?all=1&status=1")
    a.refresh_from_db()
    assert a.status == 1
    assert response.context["all_complete"] is True
    assert reverse("tasks-bulk-status") + "?all=1&status=0" in response.content.decode()

    client.post(reverse("tasks-bulk-status") + "?all=1&status=0")
    a.refresh_from_db()
    b.refresh_from_db()
    assert (a.status, b.status) == (0, 0)
