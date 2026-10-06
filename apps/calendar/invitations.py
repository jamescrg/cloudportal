"""Forwarded calendar invitations.

An invitation is an email with an iCalendar attachment. The user forwards
it to their own address on the inbound domain; Mailgun posts the parsed
message to the webhook (views.calendar_inbound), and the attachment is
read here and posted as an event. The invitation's UID is kept on the
event, so a later revision of the same invitation updates it and a
cancellation removes it.
"""

import hashlib
import hmac
import logging
import secrets
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from email.utils import parseaddr
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.mail import send_mail
from icalendar import Calendar

import apps.calendar.sync as sync
from accounts.models import CustomUser
from apps.calendar.events import default_end_time, fit_description
from apps.calendar.models import Event, is_zone

logger = logging.getLogger(__name__)

ADDRESS_PREFIX = "calendar-"


@dataclass
class Invitation:
    uid: str
    sequence: int
    cancelled: bool
    summary: str
    location: str
    date: date
    end_date: date | None
    start_time: object
    end_time: object


# --- the address ----------------------------------------------------------


def new_token():
    return secrets.token_hex(8)


def inbound_address(user):
    """The address this user forwards invitations to, or None until the
    server has a domain and the user an address."""
    if not settings.CALENDAR_INBOUND_DOMAIN or not user.calendar_inbound_token:
        return None
    return f"{ADDRESS_PREFIX}{user.calendar_inbound_token}@{settings.CALENDAR_INBOUND_DOMAIN}"


def user_for_recipient(recipient):
    """The user whose forwarding address a message was sent to, or None."""
    address = parseaddr(recipient)[1].lower()
    local, _, domain = address.partition("@")
    if (
        settings.CALENDAR_INBOUND_DOMAIN
        and domain != settings.CALENDAR_INBOUND_DOMAIN.lower()
    ):
        return None
    if not local.startswith(ADDRESS_PREFIX):
        return None
    token = local.removeprefix(ADDRESS_PREFIX)
    if not token:
        return None
    return CustomUser.objects.filter(calendar_inbound_token=token).first()


def allowed_senders(user):
    """The addresses the user may forward from: their own, and the ones
    listed in Settings."""
    senders = set()
    if user.email:
        senders.add(user.email.lower())
    for line in user.calendar_forward_from.replace(",", "\n").splitlines():
        address = parseaddr(line.strip())[1].lower()
        if address:
            senders.add(address)
    return senders


# --- the webhook post -----------------------------------------------------


def signature_is_valid(post):
    """Whether a webhook post carries Mailgun's signature for its timestamp
    and token. Always false until the signing key is configured."""
    key = settings.MAILGUN_WEBHOOK_SIGNING_KEY
    if not key:
        return False
    message = f"{post.get('timestamp', '')}{post.get('token', '')}".encode()
    expected = hmac.new(key.encode(), message, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, post.get("signature", ""))


def calendar_text(request):
    """The iCalendar text in a posted message: the .ics attachment, or a
    calendar block pasted in the body. None when there is neither."""
    for upload in request.FILES.values():
        name = (upload.name or "").lower()
        if upload.content_type == "text/calendar" or name.endswith(".ics"):
            return upload.read().decode("utf-8", "replace")

    for value in request.POST.values():
        start = value.find("BEGIN:VCALENDAR")
        if start != -1:
            end = value.find("END:VCALENDAR", start)
            if end != -1:
                stop = end + len("END:VCALENDAR")
                return value[start:stop]
    return None


# --- reading the invitation -----------------------------------------------


def _local(value, zone):
    """A date stays a date; a datetime becomes a naive datetime in the
    zone. One with no zone of its own is taken to be in it already."""
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(ZoneInfo(zone))
        return value.replace(tzinfo=None)
    return value


def parse_invitation(text, zone=None):
    """The first event in iCalendar text, read in the zone (the user's),
    or None when there is none."""
    zone = zone if is_zone(zone) else settings.TIME_ZONE
    calendar = Calendar.from_ical(text)
    events = list(calendar.walk("VEVENT"))
    if not events:
        return None
    vevent = events[0]

    method = str(calendar.get("METHOD", "")).upper()
    status = str(vevent.get("STATUS", "")).upper()

    start = _local(vevent.get("DTSTART").dt, zone)
    end_property = vevent.get("DTEND")
    end = _local(end_property.dt, zone) if end_property is not None else None
    duration = vevent.get("DURATION")
    if end is None and duration is not None:
        end = start + duration.dt

    if isinstance(start, datetime):
        event_date, start_time = start.date(), start.time()
        if not isinstance(end, datetime) or end <= start:
            end = datetime.combine(
                event_date, default_end_time(start_time) or start_time
            )
        end_date = end.date() if end.date() > event_date else None
        end_time = end.time()
    else:
        # All-day: the iCalendar end is the day after the last day
        event_date, start_time, end_time = start, None, None
        end_date = None
        if isinstance(end, date):
            last = end - timedelta(days=1)
            if last > event_date:
                end_date = last

    return Invitation(
        uid=str(vevent.get("UID", "")).strip(),
        sequence=int(vevent.get("SEQUENCE", 0) or 0),
        cancelled=method == "CANCEL" or status == "CANCELLED",
        summary=str(vevent.get("SUMMARY", "")).strip(),
        location=str(vevent.get("LOCATION", "")).strip(),
        date=event_date,
        end_date=end_date,
        start_time=start_time,
        end_time=end_time,
    )


# --- posting it -----------------------------------------------------------


def post_invitation(user, invitation):
    """Put the invitation on the user's calendar.

    Returns (outcome, event): 'created' or 'updated' with the event;
    'cancelled' with the event just removed; 'stale' when an older revision
    of an invitation already posted arrives; 'missing' for a cancellation
    of an event that is not here.
    """
    existing = None
    if invitation.uid:
        existing = Event.objects.filter(user=user, ical_uid=invitation.uid).first()

    if invitation.cancelled:
        if existing is None:
            return "missing", None
        sync.delete_event_remote(existing)
        existing.delete()
        return "cancelled", existing

    if existing is not None and invitation.sequence < existing.ical_sequence:
        return "stale", existing

    event = existing or Event(user=user, ical_uid=invitation.uid or None)
    event.description = fit_description(invitation.summary or "Untitled")
    event.date = invitation.date
    event.end_date = invitation.end_date
    event.start_time = invitation.start_time
    event.end_time = invitation.end_time
    location_limit = Event._meta.get_field("location").max_length
    event.location = invitation.location[:location_limit] or None
    event.ical_sequence = invitation.sequence
    event.time_zone = user.time_zone
    event.save()
    sync.push_event(event)
    return ("updated" if existing else "created"), event


# --- telling the user -----------------------------------------------------


def notify(user, subject, body):
    """A short note back to the user about a forwarded invitation. A
    failure to send is logged; the webhook's answer does not depend on it."""
    recipient = user.notification_email or user.email
    if not recipient:
        return
    try:
        send_mail(
            subject, body, settings.SERVER_EMAIL, [recipient], fail_silently=False
        )
    except Exception:
        logger.exception("Could not send the invitation note to %s", recipient)


def describe(event):
    shown = event.in_zone(event.user.time_zone)
    when = shown.date.strftime("%a, %b %-d")
    if shown.end_date:
        when += shown.end_date.strftime(" to %a, %b %-d")
    if shown.start_time:
        when += " at " + shown.start_time.strftime("%-I:%M %p")
    return f"{event.description} on {when}"
