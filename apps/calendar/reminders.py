"""Sending event notifications.

A notification is due once its time has come and it has not been sent for
that time. The time is worked out from the event as it stands now, so an
event that moves is notified again at its new time, and one whose time
passed long ago (a notification added late, or an event moved into the
past) is let go rather than sent stale.
"""

from datetime import timedelta
from logging import getLogger

from django.utils import timezone

from apps.calendar.models import EventReminder
from config.email import send_event_reminder_email

logger = getLogger(__name__)

# How long after its time a notification is still worth sending
GRACE = timedelta(hours=2)


def due_reminders(now=None):
    """The notifications to send now, as (reminder, fire_at) pairs, and the
    ones too old to send, which are marked as passed."""
    now = now or timezone.now()
    due = []
    candidates = EventReminder.objects.filter(
        event__date__gte=(now - timedelta(days=60)).date()
    ).select_related("event", "event__user")
    for reminder in candidates:
        fire_at = reminder.fire_at
        if fire_at > now or reminder.sent_for == fire_at:
            continue
        if now - fire_at > GRACE:
            EventReminder.objects.filter(pk=reminder.pk).update(sent_for=fire_at)
            continue
        due.append((reminder, fire_at))
    return due


def send_due(now=None):
    """Send every notification that is due. Returns (sent, errors)."""
    sent = errors = 0
    for reminder, fire_at in due_reminders(now):
        result = send_event_reminder_email(reminder.event.user, reminder.event)
        if result["success"]:
            EventReminder.objects.filter(pk=reminder.pk).update(sent_for=fire_at)
            sent += 1
        else:
            errors += 1
    return sent, errors
