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
from apps.calendar.events import show_tasks
from apps.calendar.models import Event
from apps.tasks.models import Task

# How many days the calendar strip shows, today first
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


def _entry_for_event(event, zone):
    """An event as the strip shows it: its description, and its start
    time where the user is (None for an all-day event)."""
    shown = event.in_zone(zone)
    return SimpleNamespace(
        kind="event",
        id=event.id,
        title=event.description or "Untitled",
        time=shown.start_time,
        repeat_summary=event.series.summary if event.series_id else "",
        first_day=shown.date,
        last_day=shown.end_date or shown.date,
    )


def _entry_for_task(task, zone):
    """A task as the strip shows it, beside the events of its due day."""
    shown = task.in_zone(zone)
    return SimpleNamespace(
        kind="task",
        id=task.id,
        title=task.title,
        time=shown.due_time,
        repeat_summary=task.repeat_summary if task.parent_task_id else "",
        first_day=shown.due_date,
        last_day=shown.due_date,
    )


def _entry_key(entry):
    """All-day entries first, then by time, events before tasks at the
    same time, then by title."""
    return (
        entry.time is not None,
        entry.time or time.min,
        entry.kind != "event",
        entry.title.lower(),
    )


def week_days(request, today=None):
    """The next seven days, each with the entries the strip shows on it.

    A day carries its date, its label (Today, Tomorrow, a weekday), the
    entries that fit, and how many more there are. An event over several
    days appears on each day it covers. Tasks join the events when the
    calendar's own show-tasks switch is on.
    """
    user = request.user
    zone = user.time_zone
    today = today or timezone.localdate()
    last = today + timedelta(days=WEEK_DAYS - 1)

    # A day's margin each side covers a timed event whose date reads
    # differently in the user's zone than in its own
    first_touch, last_touch = today - timedelta(days=1), last + timedelta(days=1)
    recurrence.extend_for(user, last_touch, today)
    events = (
        Event.objects.filter(user=user, date__lte=last_touch)
        .filter(Q(end_date__gte=first_touch) | Q(end_date=None, date__gte=first_touch))
        .select_related("series")
    )
    entries = [_entry_for_event(event, zone) for event in events]

    if show_tasks(request):
        tasks = Task.objects.filter(
            user=user,
            status=0,
            archived=False,
            is_recurring=False,
            due_date__gte=first_touch,
            due_date__lte=last_touch,
        ).select_related("parent_task")
        entries.extend(_entry_for_task(task, zone) for task in tasks)

    days = []
    for offset in range(WEEK_DAYS):
        day = today + timedelta(days=offset)
        on_day = sorted(
            (e for e in entries if e.first_day <= day <= e.last_day), key=_entry_key
        )
        days.append(
            SimpleNamespace(
                date=day,
                label=day_label(day, today),
                is_today=day == today,
                entries=on_day[:DAY_LIMIT],
                more=max(len(on_day) - DAY_LIMIT, 0),
                count=len(on_day),
            )
        )
    return days


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
