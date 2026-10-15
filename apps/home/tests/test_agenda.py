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
SUNDAY = date(2030, 3, 3)  # the first day of its week
WED = 3  # today's place in the week


def _request(user, show_tasks=False):
    request = RequestFactory().get("/")
    request.user = user
    request.session = {SHOW_TASKS_KEY: True} if show_tasks else {}
    return request


def _titles(day):
    return [entry.title for entry in day.entries]


def test_week_runs_sunday_to_saturday_round_today(user):
    week = agenda.week_days(_request(user), today=TODAY)
    assert [day.date for day in week] == [SUNDAY + timedelta(days=i) for i in range(7)]
    assert [day.label for day in week] == [
        "Sun",
        "Mon",
        "Tue",
        "Wed",
        "Thu",
        "Fri",
        "Sat",
    ]
    assert [day.is_today for day in week] == [False] * WED + [True] + [False] * 3
    assert all(day.count == 0 for day in week)


@pytest.mark.parametrize(
    "day", [SUNDAY, TODAY, SUNDAY + timedelta(days=6)], ids=["sun", "wed", "sat"]
)
def test_any_day_of_a_week_gives_that_week(user, day):
    week = agenda.week_days(_request(user), today=TODAY, week_of=day)
    assert week[0].date == SUNDAY


def test_another_week_has_no_today(user):
    week = agenda.week_days(
        _request(user), today=TODAY, week_of=TODAY + timedelta(days=7)
    )
    assert week[0].date == SUNDAY + timedelta(days=7)
    assert not any(day.is_today for day in week)


def test_short_time_is_the_month_views():
    assert agenda.short_time(time(9, 30)) == "9:30a"
    assert agenda.short_time(time(13, 0)) == "1p"
    assert agenda.short_time(time(0, 5)) == "12:05a"
    assert agenda.short_time(time(12, 0)) == "12p"


def test_week_context_steps_a_week_each_way(user):
    context = agenda.week_context(
        _request(user), week_of=date(2030, 3, 27), today=TODAY
    )
    assert context["week"][0].date == date(2030, 3, 24)
    assert context["week_previous"] == date(2030, 3, 17)
    assert context["week_next"] == date(2030, 3, 31)
    assert context["week_range"] == "Mar 24 – 30"
    assert context["week_is_current"] is False
    assert agenda.week_context(_request(user), today=TODAY)["week_is_current"]


def test_week_range_across_months_and_years():
    assert agenda.week_range(date(2030, 3, 31), TODAY) == "Mar 31 – Apr 6"
    assert agenda.week_range(date(2030, 12, 29), TODAY) == "Dec 29 – Jan 4, 2031"
    assert agenda.week_range(date(2031, 3, 2), TODAY) == "Mar 2 – 8, 2031"


def test_events_fall_on_their_days_all_day_first(user):
    Event.objects.create(
        user=user, date=TODAY, description="Dentist", start_time=time(9, 0)
    )
    Event.objects.create(user=user, date=TODAY, description="Holiday")
    Event.objects.create(user=user, date=TODAY + timedelta(days=2), description="Gig")
    Event.objects.create(user=user, date=TODAY + timedelta(days=7), description="Far")
    Event.objects.create(user=user, date=SUNDAY - timedelta(days=1), description="Gone")
    week = agenda.week_days(_request(user), today=TODAY)
    assert _titles(week[WED]) == ["Holiday", "Dentist"]
    assert week[WED].entries[1].time == time(9, 0)
    assert week[WED].entries[1].time_label == "9a"
    assert week[WED].entries[0].time_label == ""
    assert _titles(week[WED + 2]) == ["Gig"]
    assert sum(day.count for day in week) == 3


def test_multi_day_event_shows_on_each_day(user):
    Event.objects.create(
        user=user,
        date=TODAY - timedelta(days=1),
        end_date=TODAY + timedelta(days=1),
        description="Conference",
    )
    week = agenda.week_days(_request(user), today=TODAY)
    assert _titles(week[WED - 2]) == []
    assert _titles(week[WED - 1]) == ["Conference"]
    assert _titles(week[WED]) == ["Conference"]
    assert _titles(week[WED + 1]) == ["Conference"]
    assert _titles(week[WED + 2]) == []


def test_busy_day_folds_past_the_limit(user):
    for i in range(agenda.DAY_LIMIT + 2):
        Event.objects.create(user=user, date=TODAY, description=f"Thing {i}")
    week = agenda.week_days(_request(user), today=TODAY)
    assert len(week[WED].entries) == agenda.DAY_LIMIT
    assert week[WED].more == 2
    assert week[WED].count == agenda.DAY_LIMIT + 2


def test_tasks_stay_off_the_strip_even_when_the_calendar_shows_them(user):
    Task.objects.create(
        user=user, title="Pay rent", due_date=TODAY, due_time=time(9, 0)
    )
    Event.objects.create(
        user=user, date=TODAY, description="Standup", start_time=time(9, 0)
    )
    assert _titles(agenda.week_days(_request(user), today=TODAY)[WED]) == ["Standup"]
    with_tasks = agenda.week_days(_request(user, show_tasks=True), today=TODAY)
    assert _titles(with_tasks[WED]) == ["Standup"]


def test_other_users_events_stay_off_the_strip(user):
    from accounts.models import CustomUser

    other = CustomUser.objects.create_user("Nico", "nico@gmail.com", "clawboy")
    Event.objects.create(user=other, date=TODAY, description="Theirs")
    week = agenda.week_days(_request(user), today=TODAY)
    assert week[WED].count == 0


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


def test_home_page_keeps_an_empty_week_for_its_chevrons(client):
    response = client.get(reverse("home"))
    assert response.status_code == 200
    page = response.content.decode()
    assert "From Your Calendar" in page
    assert "Nothing on the calendar this week." in page


def test_the_chevrons_swap_in_another_week(client, user):
    Event.objects.create(
        user=user, date=date.today() + timedelta(days=7), description="Next week thing"
    )
    page = client.get(reverse("home")).content.decode()
    week = agenda.week_start(date.today())
    assert reverse("home-week", args=[str(week + timedelta(days=7))]) in page
    assert reverse("home-week", args=[str(week - timedelta(days=7))]) in page

    response = client.get(reverse("home-week", args=[str(week + timedelta(days=7))]))
    assert response.status_code == 200
    card = response.content.decode()
    assert 'id="home-week"' in card
    assert "Next week thing" in card
    assert "This week" in card


def test_an_empty_week_still_comes_back_from_the_chevrons(client):
    response = client.get(reverse("home-week", args=["2031-01-08"]))
    assert response.status_code == 200
    card = response.content.decode()
    assert "Jan 5 – 11, 2031" in card
    assert "Nothing on the calendar this week." in card


def test_the_chevrons_want_a_date(client):
    assert client.get(reverse("home-week", args=["soon"])).status_code == 404


def test_another_users_events_stay_off_another_week(client, user):
    from accounts.models import CustomUser

    other = CustomUser.objects.create_user("Nico", "nico@gmail.com", "clawboy")
    Event.objects.create(user=other, date=date(2031, 1, 8), description="Theirs")
    card = client.get(reverse("home-week", args=["2031-01-08"])).content.decode()
    assert "Theirs" not in card
