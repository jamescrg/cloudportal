"""The home page's calendar card: a week of the user's calendar, Sunday to
Saturday, as a one-week slice of the calendar's month view. FullCalendar
draws it from week_feed through the calendar's own component
(events-calendar.js), so its events and tasks drag from day to day and a
click on a day adds an event on it, as on the calendar.

It comes from the app's own data. The feed reads the Event model, which
the calendar app keeps in step with Google, so a user whose events live on
Google sees them here without the home page talking to Google itself. It
shows every event of the user's, whatever the calendar's filter. Where the
home page's setting has them, the user's open tasks are on their days too,
and on the week holding today any overdue from before it are gathered on
today.
"""

from datetime import timedelta

from django.db.models import Q

from apps.calendar import recurrence
from apps.calendar.feed import event_entry, task_entry
from apps.calendar.models import Event
from apps.tasks.models import Task


def week_start(day):
    """The Sunday on or before the day: the first day of its week."""
    return day - timedelta(days=(day.weekday() + 1) % 7)


def week_feed(user, first, last, today, show_tasks=False):
    """The entries from first to last (inclusive) as FullCalendar takes
    them: the user's events that touch those days and, with show_tasks,
    their open tasks due in them. When the days hold today, the tasks due
    before them, however long ago, are gathered on today."""
    # A day's margin each side covers a timed entry whose date reads
    # differently in the browser's zone than in its own
    first_touch, last_touch = first - timedelta(days=1), last + timedelta(days=1)
    recurrence.extend_for(user, last_touch, today)
    events = (
        Event.objects.filter(user=user, date__lte=last_touch)
        .filter(Q(end_date__gte=first_touch) | Q(end_date=None, date__gte=first_touch))
        .select_related("series")
    )
    entries = [event_entry(event) for event in events]
    if not show_tasks:
        return entries

    gather = first <= today <= last
    tasks = Task.objects.filter(
        user=user,
        status=0,
        is_recurring=False,
        archived=False,
        due_date__lte=last_touch,
    )
    if not gather:
        tasks = tasks.filter(due_date__gte=first_touch)
    for task in tasks:
        due = task.in_zone(user.time_zone).due_date
        if gather and due < first:
            entries.append(task_entry(task, day=today, due_date=due))
        elif due >= first_touch:
            entries.append(task_entry(task))
    return entries
