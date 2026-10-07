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

from datetime import time, timedelta

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.calendar.models import (
    Event,
    EventReminder,
    EventSeries,
    PendingGoogleDeletion,
)
from apps.common import recurrence as rules
from apps.common.recurrence import REPEAT_CHOICES, WEEKDAYS, nth_weekday  # noqa: F401

HORIZON = timedelta(days=365)


def horizon(today=None):
    """The last day occurrences are made through."""
    return (today or timezone.localdate()) + HORIZON


# The rule arithmetic is shared with recurring tasks (apps.common.recurrence);
# these take a series, as the calendar's code and tests do.

rule_for = rules.pattern_for


def rule_of(series):
    """The pattern a series keeps, in the shape rule_for gives."""
    return series.rule.pattern()


def repeat_of(series):
    """The form's Repeat choice for a series."""
    return rules.repeat_of(series.rule)


def form_initial(series):
    """The Repeat fields' starting values for an occurrence of a series."""
    return rules.form_initial(series.rule)


def days_between(series, after, through):
    """The days the series falls on after one day and up to another."""
    return rules.days_between(series.rule, after, through)


def describe(series):
    """The series' rule in words ("Weekly on Tuesday and Thursday")."""
    return rules.describe(series.rule)


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


# The furthest ahead a look at the calendar makes occurrences
FURTHEST = timedelta(days=365 * 10)


def extend_for(user, through, today=None):
    """Make a user's occurrences up to a day the calendar is showing, past
    the year made ahead (but never more than ten years out). Returns how
    many were made."""
    today = today or timezone.localdate()
    through = min(through, today + FURTHEST)
    made = 0
    running = EventSeries.objects.filter(
        user=user, generated_through__lt=through
    ).exclude(until__lte=F("generated_through"))
    for series in running:
        made += generate(series, through)
    return made


def update_following(series, event):
    """Carry an edit of one occurrence (its description, times, place and
    length) to the later occurrences and to the series, leaving each on
    its own day. The occurrences keep their notifications and their Google
    events, which take the change on the next sync."""
    span = (event.end_date - event.date).days if event.end_date else 0
    fields = {
        "description": event.description,
        "start_time": event.start_time,
        "end_time": event.end_time,
        "time_zone": event.time_zone,
        "location": event.location,
    }
    with transaction.atomic():
        for occurrence in series.occurrences.filter(date__gt=event.date):
            for name, value in fields.items():
                setattr(occurrence, name, value)
            occurrence.end_date = (
                occurrence.date + timedelta(days=span) if span else None
            )
            occurrence.save()
        for name, value in fields.items():
            setattr(series, name, value)
        series.span_days = span
        series.save()
