"""Sending event notifications (see apps.common.reminders)."""

from apps.calendar.models import EventReminder
from apps.common.reminders import send_due as _send_due
from config.email import send_event_reminder_email


def send_due(now=None):
    """Send every event notification that is due. Returns (sent, errors)."""
    queryset = EventReminder.objects.select_related("event", "event__user")
    return _send_due(queryset, send_event_reminder_email, now)
