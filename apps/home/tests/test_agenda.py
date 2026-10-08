"""The home page's week strip and scheduled tasks come from the app's own
calendar and tasks."""

from datetime import date, time, timedelta

import pytest
from django.test import RequestFactory
from django.urls import reverse

from apps.calendar.events import SHOW_TASKS_KEY
from apps.calendar.models import Event
from apps.folders.models import Folder
from apps.home import agenda
from apps.tasks.models import Task

pytestmark = pytest.mark.django_db

TODAY = date(2030, 3, 6)  # a Wednesday


def _request(user, show_tasks=False):
    request = RequestFactory().get("/")
    request.user = user
    request.session = {SHOW_TASKS_KEY: True} if show_tasks else {}
    return request


def _titles(day):
    return [entry.title for entry in day.entries]


def test_week_runs_seven_days_from_today(user):
    week = agenda.week_days(_request(user), today=TODAY)
    assert [day.date for day in week] == [TODAY + timedelta(days=i) for i in range(7)]
    assert [day.label for day in week][:3] == ["Today", "Tomorrow", "Friday"]
    assert week[0].is_today and not week[1].is_today
    assert all(day.count == 0 for day in week)


def test_events_fall_on_their_days_all_day_first(user):
    Event.objects.create(
        user=user, date=TODAY, description="Dentist", start_time=time(9, 0)
    )
    Event.objects.create(user=user, date=TODAY, description="Holiday")
    Event.objects.create(user=user, date=TODAY + timedelta(days=2), description="Gig")
    Event.objects.create(user=user, date=TODAY + timedelta(days=7), description="Far")
    Event.objects.create(user=user, date=TODAY - timedelta(days=1), description="Gone")
    week = agenda.week_days(_request(user), today=TODAY)
    assert _titles(week[0]) == ["Holiday", "Dentist"]
    assert week[0].entries[1].time == time(9, 0)
    assert _titles(week[2]) == ["Gig"]
    assert sum(day.count for day in week) == 3


def test_multi_day_event_shows_on_each_day(user):
    Event.objects.create(
        user=user,
        date=TODAY - timedelta(days=1),
        end_date=TODAY + timedelta(days=1),
        description="Conference",
    )
    week = agenda.week_days(_request(user), today=TODAY)
    assert _titles(week[0]) == ["Conference"]
    assert _titles(week[1]) == ["Conference"]
    assert _titles(week[2]) == []


def test_busy_day_folds_past_the_limit(user):
    for i in range(agenda.DAY_LIMIT + 2):
        Event.objects.create(user=user, date=TODAY, description=f"Thing {i}")
    week = agenda.week_days(_request(user), today=TODAY)
    assert len(week[0].entries) == agenda.DAY_LIMIT
    assert week[0].more == 2
    assert week[0].count == agenda.DAY_LIMIT + 2


def test_tasks_join_the_strip_only_when_the_calendar_shows_them(user):
    Task.objects.create(
        user=user, title="Pay rent", due_date=TODAY, due_time=time(9, 0)
    )
    Event.objects.create(
        user=user, date=TODAY, description="Standup", start_time=time(9, 0)
    )
    Task.objects.create(user=user, title="Done", due_date=TODAY, status=1)
    without = agenda.week_days(_request(user), today=TODAY)
    assert _titles(without[0]) == ["Standup"]
    with_tasks = agenda.week_days(_request(user, show_tasks=True), today=TODAY)
    assert _titles(with_tasks[0]) == ["Standup", "Pay rent"]
    assert with_tasks[0].entries[1].kind == "task"


def test_other_users_events_stay_off_the_strip(user):
    from accounts.models import CustomUser

    other = CustomUser.objects.create_user("Nico", "nico@gmail.com", "clawboy")
    Event.objects.create(user=other, date=TODAY, description="Theirs")
    week = agenda.week_days(_request(user), today=TODAY)
    assert week[0].count == 0


def test_due_tasks_group_by_day_with_overdue_first(user):
    folder = Folder.objects.create(user=user, name="Home", page="tasks")
    Task.objects.create(user=user, title="Old", due_date=TODAY - timedelta(days=9))
    Task.objects.create(user=user, title="Late", due_date=TODAY - timedelta(days=1))
    Task.objects.create(
        user=user, title="Noon", due_date=TODAY, due_time=time(12, 0), folder=folder
    )
    Task.objects.create(user=user, title="Any time", due_date=TODAY)
    Task.objects.create(user=user, title="Soon", due_date=TODAY + timedelta(days=3))
    Task.objects.create(user=user, title="Later", due_date=TODAY + timedelta(days=4))
    Task.objects.create(user=user, title="Done", due_date=TODAY, status=1)
    Task.objects.create(user=user, title="Undated")
    groups = agenda.due_task_groups(user, today=TODAY)
    assert [g.label for g in groups] == ["Overdue", "Today", "Saturday"]
    assert groups[0].overdue and not groups[1].overdue
    assert [t.title for t in groups[0].tasks] == ["Old", "Late"]
    assert [t.title for t in groups[1].tasks] == ["Any time", "Noon"]
    assert [t.title for t in groups[2].tasks] == ["Soon"]


def test_home_page_renders_both_panels(client, user):
    user.home_due_tasks = 1
    user.save()
    Event.objects.create(user=user, date=date.today(), description="Dentist")
    Task.objects.create(user=user, title="Pay rent", due_date=date.today())
    Task.objects.create(
        user=user, title="Forgotten", due_date=date.today() - timedelta(days=2)
    )
    response = client.get(reverse("home"))
    assert response.status_code == 200
    page = response.content.decode()
    assert "From Your Calendar" in page
    assert "Dentist" in page
    assert "Scheduled Tasks" in page
    assert "Overdue" in page
    assert "Forgotten" in page
    assert "Pay rent" in page
    # the rows carry the tasks page's priority classes and flag icons
    assert 'class="priority-normal' in page
    assert "icon-equal priority-normal" in page


def test_home_page_leaves_an_empty_week_out(client):
    response = client.get(reverse("home"))
    assert response.status_code == 200
    assert "From Your Calendar" not in response.content.decode()
