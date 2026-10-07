"""Repeating events.

A repeating event is an EventSeries (the rule, and what each occurrence is)
and its occurrences, which are ordinary Event rows. Occurrences are made a
year ahead (HORIZON) when the series starts and topped up each day by the
extend_event_series command, so reminders, Google sync, dragging, the list
and the agenda all work on an occurrence as on any event.

An edit to "this and following events" ends the series the day before the
edited occurrence and starts a new one from it, the way Google Calendar
splits a series. Occurrences removed in bulk leave Google through the
deletion queue (sync.reconcile drains it), so a long series never ties up
a request with one call per occurrence; the new ones reach Google the same
way, as events never pushed.
"""

from datetime import datetime, time, timedelta

from dateutil import rrule
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.calendar.models import (
    Event,
    EventReminder,
    EventSeries,
    PendingGoogleDeletion,
)

HORIZON = timedelta(days=365)

WEEKDAYS = "0,1,2,3,4"  # Monday to Friday

FREQUENCIES = {
    "daily": rrule.DAILY,
    "weekly": rrule.WEEKLY,
    "monthly": rrule.MONTHLY,
    "yearly": rrule.YEARLY,
}

# The form's Repeat choices, each a frequency and what it fixes
REPEAT_CHOICES = [
    ("", "Does not repeat"),
    ("daily", "Daily"),
    ("weekdays", "Every weekday (Monday to Friday)"),
    ("weekly", "Weekly"),
    ("monthly", "Monthly on the same day"),
    ("monthly_weekday", "Monthly on the same weekday"),
    ("yearly", "Yearly"),
]


def horizon(today=None):
    """The last day occurrences are made through."""
    return (today or timezone.localdate()) + HORIZON


def nth_weekday(day):
    """Which of its weekday in the month a day is: 1 for the first Tuesday.
    A fifth is the month's last, and repeats as the last (-1), since most
    months have no fifth."""
    nth = (day.day - 1) // 7 + 1
    return -1 if nth == 5 else nth


def rule_for(repeat, interval, weekdays, start, until=None, count=None):
    """A rule (the fields an EventSeries keeps) from the form's choices, or
    None for an event that does not repeat. A weekly rule with no days
    chosen falls on the start's weekday."""
    if not repeat:
        return None
    rule = {
        "frequency": repeat,
        "interval": interval or 1,
        "weekdays": "",
        "monthly_by": "day",
        "until": until,
        "count": count,
    }
    if repeat == "weekdays":
        rule.update(frequency="weekly", interval=1, weekdays=WEEKDAYS)
    elif repeat == "weekly":
        days = sorted({int(d) for d in weekdays or []}) or [start.weekday()]
        rule["weekdays"] = ",".join(str(d) for d in days)
    elif repeat == "monthly_weekday":
        rule.update(frequency="monthly", monthly_by="weekday")
    return rule


def rule_of(series):
    """The rule a series keeps, in the shape rule_for gives."""
    return {
        "frequency": series.frequency,
        "interval": series.interval,
        "weekdays": series.weekdays,
        "monthly_by": series.monthly_by,
        "until": series.until,
        "count": series.count,
    }


def repeat_of(series):
    """The form's Repeat choice for a series."""
    if (
        series.frequency == "weekly"
        and series.interval == 1
        and series.weekdays == WEEKDAYS
    ):
        return "weekdays"
    if series.frequency == "monthly" and series.monthly_by == "weekday":
        return "monthly_weekday"
    return series.frequency


def form_initial(series):
    """The Repeat fields' starting values for an occurrence of a series."""
    if series.until:
        ends = "on"
    elif series.count:
        ends = "after"
    else:
        ends = "never"
    return {
        "repeat": repeat_of(series),
        "interval": series.interval,
        "weekdays": [str(d) for d in series.weekday_list],
        "ends": ends,
        "until": series.until,
        "count": series.count,
    }


def _rrule(series):
    options = {
        "freq": FREQUENCIES[series.frequency],
        "interval": series.interval,
        "dtstart": datetime.combine(series.start, time.min),
    }
    if series.frequency == "weekly":
        options["byweekday"] = series.weekday_list or [series.start.weekday()]
    elif series.frequency == "monthly" and series.monthly_by == "weekday":
        weekday = rrule.weekdays[series.start.weekday()]
        options["byweekday"] = weekday(nth_weekday(series.start))
    if series.until:
        options["until"] = datetime.combine(series.until, time.max)
    elif series.count:
        options["count"] = series.count
    return rrule.rrule(**options)


def days_between(series, after, through):
    """The days the series falls on after one day and up to another."""
    rule = _rrule(series)
    first = datetime.combine(after + timedelta(days=1), time.min)
    last = datetime.combine(through, time.max)
    return [moment.date() for moment in rule.between(first, last, inc=True)]


def _reminder_template(event):
    return [
        {
            "amount": reminder.amount,
            "unit": reminder.unit,
            "time": reminder.time.isoformat() if reminder.time else None,
        }
        for reminder in event.reminders.all()
    ]


def _reminders_from(template, event):
    return [
        EventReminder(
            event=event,
            amount=item["amount"],
            unit=item["unit"],
            time=time.fromisoformat(item["time"]) if item.get("time") else None,
        )
        for item in template
    ]


def generate(series, through):
    """Make the series' occurrences after the last one made, up to a day.
    Returns how many were made."""
    if through <= series.generated_through:
        return 0
    days = days_between(series, series.generated_through, through)
    made = []
    for day in days:
        made.append(
            Event(
                user=series.user,
                series=series,
                date=day,
                end_date=(
                    day + timedelta(days=series.span_days) if series.span_days else None
                ),
                start_time=series.start_time,
                end_time=series.end_time,
                time_zone=series.time_zone,
                description=series.description,
                event_type=series.event_type,
                location=series.location,
            )
        )
    with transaction.atomic():
        made = Event.objects.bulk_create(made)
        if series.reminders:
            EventReminder.objects.bulk_create(
                [r for event in made for r in _reminders_from(series.reminders, event)]
            )
        EventSeries.objects.filter(pk=series.pk).update(generated_through=through)
        series.generated_through = through
    return len(made)


def start_series(event, rule, today=None):
    """Make a saved event the first occurrence of a new series, and make
    the occurrences after it a year ahead."""
    span = (event.end_date - event.date).days if event.end_date else 0
    series = EventSeries.objects.create(
        user=event.user,
        start=event.date,
        generated_through=event.date,
        description=event.description,
        start_time=event.start_time,
        end_time=event.end_time,
        span_days=span,
        time_zone=event.time_zone,
        event_type=event.event_type,
        location=event.location,
        reminders=_reminder_template(event),
        **rule,
    )
    # .update, not .save: joining a series is not an edit to push to Google
    Event.objects.filter(pk=event.pk).update(series=series)
    event.series = series
    generate(series, horizon(today))
    return series


def _remove(events):
    """Delete occurrences, queueing the removal of those on Google."""
    for event in events:
        if event.google_id:
            PendingGoogleDeletion.objects.get_or_create(
                user=event.user, google_id=event.google_id
            )
    Event.objects.filter(pk__in=[event.pk for event in events]).delete()


def end_before(series, day, keep=None):
    """End a series the day before a day: its occurrences from that day on
    go (but the one to keep, which leaves the series), and the rule stops
    there. A series with nothing left is deleted."""
    later = list(
        series.occurrences.filter(date__gte=day).exclude(pk=getattr(keep, "pk", None))
    )
    with transaction.atomic():
        _remove(later)
        if keep is not None:
            Event.objects.filter(pk=keep.pk).update(series=None)
            keep.series = None
        if not series.occurrences.exists():
            series.delete()
            return
        series.until = day - timedelta(days=1)
        series.count = None
        series.save(update_fields=["until", "count", "updated_at"])


def add_reminder(event, reminder):
    """A notification added to an occurrence goes on every later one too,
    and on the series, so occurrences made later have it."""
    series = event.series
    if series is None:
        return
    template = {
        "amount": reminder.amount,
        "unit": reminder.unit,
        "time": reminder.time.isoformat() if reminder.time else None,
    }
    series.reminders = [*series.reminders, template]
    series.save(update_fields=["reminders", "updated_at"])
    later = series.occurrences.filter(date__gt=event.date)
    EventReminder.objects.bulk_create(
        [r for occurrence in later for r in _reminders_from([template], occurrence)]
    )


def remove_reminder(event, reminder):
    """A notification removed from an occurrence leaves the later ones and
    the series too: those that read the same."""
    series = event.series
    if series is None:
        return
    key = (
        reminder.amount,
        reminder.unit,
        reminder.time.isoformat() if reminder.time else None,
    )
    kept, dropped = [], False
    for item in series.reminders:
        if not dropped and (item["amount"], item["unit"], item.get("time")) == key:
            dropped = True
            continue
        kept.append(item)
    series.reminders = kept
    series.save(update_fields=["reminders", "updated_at"])
    EventReminder.objects.filter(
        event__series=series,
        event__date__gt=event.date,
        amount=reminder.amount,
        unit=reminder.unit,
        time=reminder.time,
    ).delete()


def extend_all(today=None):
    """Top up every series still running to a year ahead. Returns how many
    occurrences were made."""
    through = horizon(today)
    made = 0
    # A series that has ended (its last day made already) is left alone
    running = EventSeries.objects.filter(generated_through__lt=through).exclude(
        until__lte=F("generated_through")
    )
    for series in running.iterator():
        made += generate(series, through)
    return made
