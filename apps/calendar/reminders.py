"""Sending event notifications (see apps.common.reminders), by email or
ntfy as each user chose (apps.common.notify)."""

from apps.calendar.models import EventReminder
from apps.common import notify
from apps.common.reminders import send_due as _send_due


def send_due(now=None):
    """Send every event notification that is due. Returns (sent, errors)."""
    queryset = EventReminder.objects.select_related("event", "event__user")
    return _send_due(queryset, notify.event_reminder, now)
