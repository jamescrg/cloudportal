"""A cooldown on failed sign-ins, per email address.

The first few wrong attempts are free. After that each one starts a wait
that doubles, up to a cap, and while it runs no password is checked at all.
A successful sign-in clears the slate, and so does a quiet day. It never
locks an account for good: a lockout would let anyone who knows an
address shut its owner out.

Counts live in the database, not in memory, so every gunicorn worker sees
the same ones."""

from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .models import LoginThrottle

FREE_ATTEMPTS = 5
FIRST_WAIT = timedelta(minutes=1)
LONGEST_WAIT = timedelta(minutes=15)
FORGET_AFTER = timedelta(days=1)


def _key(login):
    return (login or "").strip().lower()[:254]


def cooldown_remaining(login):
    """How long until this address may try again; zero if it may now."""
    row = LoginThrottle.objects.filter(login=_key(login)).first()
    if row is None or row.locked_until is None:
        return timedelta(0)
    return max(row.locked_until - timezone.now(), timedelta(0))


def record_failure(login):
    """Count a failed attempt, and start a wait once the free ones are used.
    Returns the wait now in force (zero if none)."""
    now = timezone.now()
    with transaction.atomic():
        row, _ = LoginThrottle.objects.select_for_update().get_or_create(
            login=_key(login), defaults={"last_failure": now}
        )
        if now - row.last_failure > FORGET_AFTER:
            row.failures = 0
        row.failures += 1
        row.last_failure = now
        over = row.failures - FREE_ATTEMPTS
        if over > 0:
            row.locked_until = now + min(FIRST_WAIT * 2 ** (over - 1), LONGEST_WAIT)
        row.save()
    return max((row.locked_until or now) - now, timedelta(0))


def record_success(login):
    """A sign-in got all the way through: forget the failures."""
    LoginThrottle.objects.filter(login=_key(login)).delete()


def describe(wait):
    """A wait as people say it: "1 minute", "8 minutes"."""
    minutes = max(1, -(-int(wait.total_seconds()) // 60))
    return f"{minutes} minute" + ("" if minutes == 1 else "s")
