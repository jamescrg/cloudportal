"""The home page's calendar card: a week of the user's calendar, with
their open tasks on it when its toggle is on.

It comes from the app's own data. The strip reads the Event model, which
the calendar app keeps in step with Google, so a user whose events live on
Google sees them here without the home page talking to Google itself.
"""

from datetime import time, timedelta
from types import SimpleNamespace

from django.db.models import Q
from django.utils import timezone

from apps.calendar import recurrence
from apps.calendar.models import Event
from apps.tasks.models import Task

# How many days the calendar strip shows: a week, Sunday first, as the
# calendar's month view has it
WEEK_DAYS = 7

# How many entries a day shows before the rest fold into a link
DAY_LIMIT = 5

# The session key for the calendar card's tasks toggle; until it is
# pressed, the home page's setting decides
SHOW_TASKS_KEY = "home_week_tasks"


def week_start(day):
    """The Sunday on or before the day: the first day of its week."""
    return day - timedelta(days=(day.weekday() + 1) % 7)


def short_time(value):
    """A time as the calendar's month view writes it: 9:30a, 1p."""
    hour = value.hour % 12 or 12
    minutes = f":{value.minute:02d}" if value.minute else ""
    return f"{hour}{minutes}{'a' if value.hour < 12 else 'p'}"


def _entry_for_event(event, zone):
    """An event as the strip shows it: its description, and its start
    time where the user is (None for an all-day event)."""
    shown = event.in_zone(zone)
    return SimpleNamespace(
        kind="event",
        id=event.id,
        title=event.description or "Untitled",
        time=shown.start_time,
        time_label=short_time(shown.start_time) if shown.start_time else "",
        repeat_summary=event.series.summary if event.series_id else "",
        overdue=False,
        first_day=shown.date,
        last_day=shown.end_date or shown.date,
    )


def _entry_for_task(task, zone, today, gather_overdue):
    """An open task as the strip shows it, on its due day where the user
    is. On this week, a task overdue from before it is gathered on today,
    marked overdue and dated in place of its time; otherwise a task off
    the week is None."""
    shown = task.in_zone(zone)
    day, overdue = shown.due_date, False
    if gather_overdue and day < week_start(today):
        day, overdue = today, True
    return SimpleNamespace(
        kind="task",
        id=task.id,
        title=task.title,
        time=None if overdue else shown.due_time,
        time_label=(
            f"{shown.due_date:%b} {shown.due_date.day}"
            if overdue
            else short_time(shown.due_time) if shown.due_time else ""
        ),
        repeat_summary="",
        overdue=overdue,
        first_day=day,
        last_day=day,
    )


def _entry_key(entry):
    """Gathered overdue tasks first, then all-day entries, then by time,
    events before tasks at the same time, then by title."""
    return (
        not entry.overdue,
        entry.time is not None,
        entry.time or time.min,
        entry.kind != "event",
        entry.title.lower(),
    )


def week_days(request, today=None, week_of=None, show_tasks=False):
    """The week, Sunday to Saturday, that holds week_of (today's week by
    default), each day with the entries the strip shows on it.

    A day carries its date, its label (the weekday, short), whether it is
    today, the entries that fit, and how many more there are. An event over
    several days appears on each day it covers. With show_tasks, the open
    tasks due in the week are on their days too, and on this week any
    overdue from before it are gathered on today.
    """
    user = request.user
    zone = user.time_zone
    today = today or timezone.localdate()
    first = week_start(week_of or today)
    last = first + timedelta(days=WEEK_DAYS - 1)

    # A day's margin each side covers a timed event whose date reads
    # differently in the user's zone than in its own
    first_touch, last_touch = first - timedelta(days=1), last + timedelta(days=1)
    recurrence.extend_for(user, last_touch, today)
    events = (
        Event.objects.filter(user=user, date__lte=last_touch)
        .filter(Q(end_date__gte=first_touch) | Q(end_date=None, date__gte=first_touch))
        .select_related("series")
    )
    entries = [_entry_for_event(event, zone) for event in events]
    if show_tasks:
        is_current = first == week_start(today)
        tasks = Task.objects.filter(
            user=user,
            status=0,
            is_recurring=False,
            archived=False,
            due_date__lte=last_touch,
        )
        # this week reaches back for every overdue task, however old
        if not is_current:
            tasks = tasks.filter(due_date__gte=first_touch)
        for task in tasks:
            entry = _entry_for_task(task, zone, today, gather_overdue=is_current)
            if first <= entry.first_day <= last:
                entries.append(entry)

    days = []
    for offset in range(WEEK_DAYS):
        day = first + timedelta(days=offset)
        on_day = sorted(
            (e for e in entries if e.first_day <= day <= e.last_day), key=_entry_key
        )
        days.append(
            SimpleNamespace(
                date=day,
                label=day.strftime("%a"),
                is_today=day == today,
                entries=on_day[:DAY_LIMIT],
                more=max(len(on_day) - DAY_LIMIT, 0),
                count=len(on_day),
            )
        )
    return days


def week_range(first, today):
    """The week's span for the card's heading: Oct 11 – 17, or Oct 25 –
    Nov 1 when it crosses a month, with the year when it is not this one."""
    last = first + timedelta(days=WEEK_DAYS - 1)
    end = f"{last.day}" if last.month == first.month else f"{last:%b} {last.day}"
    span = f"{first:%b} {first.day} – {end}"
    if last.year != today.year or first.year != today.year:
        span += f", {last.year}"
    return span


def tasks_shown(request):
    """Whether the calendar card shows tasks: as its toggle was last left
    this session, or else as the home page's setting has it."""
    shown = request.session.get(SHOW_TASKS_KEY)
    if shown is None:
        return bool(request.user.home_due_tasks)
    return shown


def week_context(request, week_of=None, today=None):
    """What the calendar card shows for the week holding week_of (today's
    week by default): its days, how many entries they hold, its span, the
    weeks either side for the chevrons, and whether its tasks are shown."""
    today = today or timezone.localdate()
    first = week_start(week_of or today)
    show_tasks = tasks_shown(request)
    week = week_days(request, today=today, week_of=first, show_tasks=show_tasks)
    return {
        "week": week,
        "week_first": first,
        "week_tasks": show_tasks,
        "week_count": sum(day.count for day in week),
        "week_range": week_range(first, today),
        "week_is_current": first == week_start(today),
        "week_today": today,
        "week_previous": first - timedelta(days=WEEK_DAYS),
        "week_next": first + timedelta(days=WEEK_DAYS),
    }
