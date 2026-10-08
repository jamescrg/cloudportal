"""Sending notifications.

A notification is due once its time has come and it has not been sent for
that time. The time is worked out from the thing as it stands now, so one
that moves is notified again at its new time, and one whose time passed
long ago (a notification added late, or a thing moved into the past) is
let go rather than sent stale.
"""

from datetime import timedelta

from django.utils import timezone

# How long after its time a notification is still worth sending
GRACE = timedelta(hours=2)


def due_reminders(queryset, now=None):
    """The notifications in the queryset to send now, as (reminder, fire_at)
    pairs. Ones too old to send are marked as passed instead."""
    now = now or timezone.now()
    due = []
    for reminder in queryset:
        fire_at = reminder.fire_at
        if fire_at is None or fire_at > now or reminder.sent_for == fire_at:
            continue
        if now - fire_at > GRACE:
            queryset.model.objects.filter(pk=reminder.pk).update(sent_for=fire_at)
            continue
        due.append((reminder, fire_at))
    return due


def send_due(queryset, send, now=None):
    """Send every notification in the queryset that is due, with
    ``send(user, target, channel)``. Returns (sent, errors)."""
    sent = errors = 0
    for reminder, fire_at in due_reminders(queryset, now):
        result = send(reminder.target_user, reminder.target, reminder.channel)
        if result["success"]:
            queryset.model.objects.filter(pk=reminder.pk).update(sent_for=fire_at)
            sent += 1
        else:
            errors += 1
    return sent, errors
