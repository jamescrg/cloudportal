"""Events and tasks as FullCalendar entries: what the calendar's feed and
the home page's calendar card hand the grid."""

from datetime import datetime, timedelta


def feed_date(value):
    """The date in one of a feed's ISO date or date-time parameters."""
    return datetime.fromisoformat(value.replace("Z", "+00:00")).date()


def event_entry(event):
    """An event as a FullCalendar entry. A timed event is sent as a moment
    with its offset, and the grid draws it in the browser's own zone.
    FullCalendar's end is exclusive, so an all-day event over several days
    ends the day after its last. A repeating event is marked, with its
    rule in words for a tooltip."""
    entry = {
        "id": str(event.id),
        "title": event.description or "Untitled",
        "extendedProps": {
            "location": event.location or "",
        },
    }
    if event.series:
        entry["className"] = "fc-event-repeats"
        entry["extendedProps"]["repeats"] = event.series.summary

    if event.start_time and event.end_time:
        entry["start"] = event.start_at.isoformat()
        entry["end"] = event.end_at.isoformat()
        entry["allDay"] = False
    elif event.start_time:
        entry["start"] = event.start_at.isoformat()
        entry["allDay"] = False
    else:
        entry["start"] = str(event.date)
        if event.end_date:
            entry["end"] = str(event.end_date + timedelta(days=1))
        entry["allDay"] = True
    return entry


def task_entry(task, day=None, due_date=None):
    """An open task as a FullCalendar entry, told from an event by its id
    prefix and its kind, which may be dragged to another day but not
    stretched: at its due moment when it has a time, else on its due day.
    Given a day, it is an overdue task gathered there (the home page's
    card): an all-day entry, in the urgent colour, carrying its due date
    (due_date, as the user sees it), which the grid writes after its box."""
    entry = {
        "id": f"task-{task.id}",
        "title": task.title,
        "className": "fc-event-task",
        "durationEditable": False,
        "extendedProps": {"kind": "task", "task_id": task.id},
    }
    if day is not None:
        entry["start"] = str(day)
        entry["allDay"] = True
        entry["className"] += " fc-event-overdue"
        entry["extendedProps"]["overdue"] = True
        due = due_date or task.due_date
        entry["extendedProps"]["due_label"] = f"{due:%b} {due.day}"
    elif task.due_time:
        entry["start"] = task.due_at.isoformat()
        entry["allDay"] = False
    else:
        entry["start"] = str(task.due_date)
        entry["allDay"] = True
    return entry
