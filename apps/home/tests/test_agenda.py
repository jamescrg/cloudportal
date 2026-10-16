"""The home page's calendar card: a week of the calendar's month view,
drawn by FullCalendar from the card's own feed of the user's events and,
where the home page's setting has them, their open tasks."""

from datetime import date, time, timedelta

import pytest
from django.urls import reverse

from apps.calendar.models import Event
from apps.home import agenda
from apps.tasks.models import Task

pytestmark = pytest.mark.django_db


@pytest.fixture
def other_user():
    from accounts.models import CustomUser

    return CustomUser.objects.create_user("Nico", "nico@gmail.com", "clawboy")


TODAY = date(2030, 3, 6)  # a Wednesday
SUNDAY = date(2030, 3, 3)  # the first day of its week
SATURDAY = date(2030, 3, 9)


def _feed(user, first=SUNDAY, last=SATURDAY, show_tasks=False):
    return agenda.week_feed(user, first, last, TODAY, show_tasks=show_tasks)


def _titles(entries):
    return sorted(entry["title"] for entry in entries)


@pytest.mark.parametrize("day", [SUNDAY, TODAY, SATURDAY])
def test_a_week_starts_on_its_sunday(day):
    assert agenda.week_start(day) == SUNDAY


def test_the_week_has_the_users_events_on_it(user):
    Event.objects.create(user=user, date=TODAY, description="Dentist")
    Event.objects.create(
        user=user, date=SUNDAY - timedelta(days=2), end_date=SUNDAY, description="Trip"
    )
    Event.objects.create(
        user=user, date=SATURDAY + timedelta(days=3), description="Later"
    )

    assert _titles(_feed(user)) == ["Dentist", "Trip"]


def test_events_are_month_view_entries(user):
    Event.objects.create(user=user, date=TODAY, description="Dentist")
    timed = Event.objects.create(
        user=user,
        date=TODAY,
        start_time=time(9, 30),
        end_time=time(10, 30),
        description="Call",
    )

    by_title = {entry["title"]: entry for entry in _feed(user)}
    assert by_title["Dentist"]["allDay"] is True
    assert by_title["Dentist"]["start"] == "2030-03-06"
    assert by_title["Call"]["allDay"] is False
    assert by_title["Call"]["id"] == str(timed.id)


def test_other_users_events_stay_off(user, other_user):
    Event.objects.create(user=other_user, date=TODAY, description="Theirs")

    assert _feed(user) == []


def test_tasks_stay_off_unless_asked_for(user):
    Task.objects.create(user=user, title="Pay rent", due_date=TODAY)

    assert _feed(user) == []


def test_open_tasks_are_on_their_days(user):
    task = Task.objects.create(user=user, title="Pay rent", due_date=TODAY)
    Task.objects.create(user=user, title="Call", due_date=TODAY, due_time=time(15))

    by_title = {entry["title"]: entry for entry in _feed(user, show_tasks=True)}
    rent = by_title["Pay rent"]
    assert rent["id"] == f"task-{task.id}"
    assert rent["start"] == "2030-03-06" and rent["allDay"] is True
    assert rent["extendedProps"] == {"kind": "task", "task_id": task.id}
    assert by_title["Call"]["allDay"] is False


def test_done_archived_template_and_undated_tasks_stay_off(user):
    Task.objects.create(user=user, title="Done", due_date=TODAY, status=1)
    Task.objects.create(user=user, title="Archived", due_date=TODAY, archived=True)
    Task.objects.create(user=user, title="Template", due_date=TODAY, is_recurring=True)
    Task.objects.create(user=user, title="Someday")

    assert _feed(user, show_tasks=True) == []


def test_overdue_from_before_the_week_gathers_on_today(user):
    Task.objects.create(
        user=user, title="Old", due_date=date(2030, 1, 15), due_time=time(9)
    )
    Task.objects.create(user=user, title="This week", due_date=SUNDAY)

    by_title = {entry["title"]: entry for entry in _feed(user, show_tasks=True)}
    old = by_title["Old"]
    assert old["start"] == str(TODAY) and old["allDay"] is True
    assert old["extendedProps"]["overdue"] is True
    assert old["extendedProps"]["due_label"] == "Jan 15"
    assert "fc-event-overdue" in old["className"]
    # one due earlier this week stays on its own day
    assert by_title["This week"]["start"] == str(SUNDAY)
    assert "overdue" not in by_title["This week"]["extendedProps"]


def test_another_week_shows_only_its_own_tasks(user):
    Task.objects.create(user=user, title="Old", due_date=date(2030, 1, 15))
    Task.objects.create(
        user=user, title="Next week", due_date=SATURDAY + timedelta(days=2)
    )

    entries = _feed(
        user,
        first=SUNDAY + timedelta(days=7),
        last=SATURDAY + timedelta(days=7),
        show_tasks=True,
    )
    assert _titles(entries) == ["Next week"]


def test_other_users_tasks_stay_off(user, other_user):
    Task.objects.create(user=other_user, title="Theirs", due_date=TODAY)

    assert _feed(user, show_tasks=True) == []


# --- the feed and the card ---------------------------------------------------


def _get_feed(
    client, start="2030-03-03T00:00:00-05:00", end="2030-03-10T00:00:00-05:00"
):
    return client.get(reverse("home-week-feed"), {"start": start, "end": end})


def test_the_feed_serves_the_week_fullcalendar_asks_for(client, user):
    Event.objects.create(user=user, date=TODAY, description="Dentist")
    Event.objects.create(user=user, date=date(2030, 3, 12), description="Next week")

    response = _get_feed(client)

    assert response.status_code == 200
    assert _titles(response.json()) == ["Dentist"]


def test_the_feed_has_tasks_where_the_setting_has_them(client, user):
    Task.objects.create(user=user, title="Pay rent", due_date=TODAY)
    assert _get_feed(client).json() == []

    user.home_due_tasks = 1
    user.save()
    assert _titles(_get_feed(client).json()) == ["Pay rent"]


def test_the_feed_wants_dates(client):
    assert _get_feed(client, start="soon").status_code == 400


def test_the_feed_wants_a_login(client, user):
    client.logout()

    assert _get_feed(client).status_code == 302


def test_the_card_is_the_calendars_component_on_the_feed(client, user):
    page = client.get(reverse("home")).content.decode()

    assert "<h1>Calendar</h1>" in page
    assert "eventsCalendar({week: true" in page
    assert reverse("home-week-feed") in page
    # the grid is the calendar's own, so the page loads it
    assert "fullcalendar@" in page and "events-calendar.js" in page
    assert "app-calendar.css" in page


def test_without_the_card_the_page_leaves_the_grid_unloaded(client, user):
    user.home_events = 0
    user.save()

    page = client.get(reverse("home")).content.decode()

    assert "eventsCalendar(" not in page
    assert "fullcalendar@" not in page and "app-calendar.css" not in page
