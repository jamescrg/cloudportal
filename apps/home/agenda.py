"""The home page's two agenda panels: a week of the user's calendar, and
the tasks due soon.

Both come from the app's own data. The calendar strip reads the Event
model, which the calendar app keeps in step with Google, so a user whose
events live on Google sees them here without the home page talking to
Google itself.
"""

from datetime import time, timedelta
from types import SimpleNamespace

from django.db.models import Q
from django.utils import timezone

from apps.calendar import recurrence
from apps.calendar.models import Event
from apps.tasks.models import Task
from apps.tasks.priority import level_for

# How many days the calendar strip shows: a week, Sunday first, as the
# calendar's month view has it
WEEK_DAYS = 7

# How many entries a day shows before the rest fold into a link
DAY_LIMIT = 5

# How far ahead the scheduled tasks look
TASK_DAYS = 3


def day_label(day, today):
    """Today, Tomorrow, or the weekday's name."""
    if day == today:
        return "Today"
    if day == today + timedelta(days=1):
        return "Tomorrow"
    return day.strftime("%A")


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
        first_day=shown.date,
        last_day=shown.end_date or shown.date,
    )


def _entry_key(entry):
    """All-day entries first, then by time, at the
    same time, then by title."""
    return (
        entry.time is not None,
        entry.time or time.min,
        entry.kind != "event",
        entry.title.lower(),
    )


def week_days(request, today=None, week_of=None):
    """The week, Sunday to Saturday, that holds week_of (today's week by
    default), each day with the entries the strip shows on it.

    A day carries its date, its label (the weekday, short), whether it is
    today, the entries that fit, and how many more there are. An event over
    several days appears on each day it covers. Tasks stay off it: the
    Scheduled Tasks panel under it has them.
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


def week_context(request, week_of=None, today=None):
    """What the calendar card shows for the week holding week_of (today's
    week by default): its days, how many entries they hold, its span, and
    the weeks either side for the chevrons."""
    today = today or timezone.localdate()
    first = week_start(week_of or today)
    week = week_days(request, today=today, week_of=first)
    return {
        "week": week,
        "week_count": sum(day.count for day in week),
        "week_range": week_range(first, today),
        "week_is_current": first == week_start(today),
        "week_today": today,
        "week_previous": first - timedelta(days=WEEK_DAYS),
        "week_next": first + timedelta(days=WEEK_DAYS),
    }


def due_task_groups(user, today=None):
    """The user's open tasks due in the next few days, and any overdue,
    grouped by day for the Scheduled Tasks panel.

    Each group has a label (Overdue, Today, Tomorrow, a weekday), whether
    it is the overdue group, and its tasks ordered by day, time and title.
    A task's day is its due date where the user is now; every overdue
    task, however old, is in the one Overdue group at the top.
    """
    today = today or timezone.localdate()
    last = today + timedelta(days=TASK_DAYS)
    # A day's margin on the far side: a task due late tonight in another
    # zone may fall on tomorrow here
    tasks = Task.objects.filter(
        user=user,
        status=0,
        is_recurring=False,
        archived=False,
        due_date__lte=last + timedelta(days=1),
    ).select_related("folder", "parent_task")

    overdue = today - timedelta(days=1)
    groups = {}
    for task in tasks:
        shown = task.in_zone(user.time_zone)
        if shown.due_date > last:
            continue
        task.shown_here = shown
        # the priority as the tasks page shows it: a slug, name and icon
        task.level = level_for(task.priority)
        key = max(shown.due_date, overdue)
        groups.setdefault(key, []).append(task)

    result = []
    for key in sorted(groups):
        group_tasks = sorted(
            groups[key],
            key=lambda t: (
                t.shown_here.due_date,
                t.shown_here.due_time is not None,
                t.shown_here.due_time or time.min,
                t.title.lower(),
            ),
        )
        result.append(
            SimpleNamespace(
                date=key,
                label="Overdue" if key == overdue else day_label(key, today),
                overdue=key == overdue,
                tasks=group_tasks,
            )
        )
    return result
