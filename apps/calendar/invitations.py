"""Calendar invitations, both ways.

Forwarded in: an invitation is an email with an iCalendar attachment. The
user forwards it to their own address on the inbound domain; Mailgun
posts the parsed message to the webhook (views.calendar_inbound), and the
attachment is read here and posted as an event. The invitation's UID is
kept on the event, so a later revision of the same invitation updates it
and a cancellation removes it.

Sent out: an event's guests (EventGuest) are emailed an invitation of the
same kind (METHOD:REQUEST), which any calendar app shows with Yes, Maybe
and No. The organiser named in it is the user's forwarding address, so a
guest's answer, an email with a METHOD:REPLY attachment that their
calendar app sends on its own, comes back through the same webhook and
is recorded on the guest. A change to the event goes out again as a new
revision (SEQUENCE); a deleted event, or a guest removed, gets a
cancellation (METHOD:CANCEL).
"""

import hashlib
import hmac
import logging
import secrets
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from email.utils import formataddr, parseaddr
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.mail import EmailMultiAlternatives, send_mail
from django.utils import timezone
from icalendar import Calendar, Event as VEvent, vCalAddress, vText

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


# --- inviting guests ------------------------------------------------------

PRODID = "-//Cloud Portal//Calendar//EN"
UTC = ZoneInfo("UTC")
ANSWERS = {"accepted", "declined", "tentative"}


def organiser_address(user):
    """The address the user's invitations name as organiser, which their
    guests' answers come back to: their forwarding address. None until
    they have one."""
    return inbound_address(user)


def organiser_name(user):
    return user.get_full_name() or user.username


def can_invite(user):
    return organiser_address(user) is not None


def details(event):
    """What the guests were told: a change to any of it sends the
    invitation again."""
    return (
        event.date,
        event.end_date,
        event.start_time,
        event.end_time,
        event.time_zone,
        event.description,
        event.location,
    )


def _ensure_uid(event):
    if not event.invite_uid:
        domain = settings.CALENDAR_INBOUND_DOMAIN or "cloudportal"
        event.invite_uid = f"{uuid.uuid4()}@{domain}"
        event.save(update_fields=["invite_uid"])


def _vevent(event, guests, method):
    vevent = VEvent()
    vevent.add("uid", event.invite_uid)
    vevent.add("sequence", event.invite_sequence)
    vevent.add("dtstamp", datetime.now(UTC))
    vevent.add("summary", event.description or "Untitled")
    if event.location:
        vevent.add("location", event.location)
    if event.start_time:
        # A moment, given in UTC, which every calendar app reads
        start = event.start_at
        end = event.end_at or start + timedelta(hours=1)
        vevent.add("dtstart", start.astimezone(UTC))
        vevent.add("dtend", end.astimezone(UTC))
    else:
        # All-day: the iCalendar end is the day after the last day
        vevent.add("dtstart", event.date)
        vevent.add("dtend", event.last_date + timedelta(days=1))
    vevent.add("status", "CANCELLED" if method == "CANCEL" else "CONFIRMED")
    organiser = vCalAddress(f"mailto:{organiser_address(event.user)}")
    organiser.params["CN"] = vText(organiser_name(event.user))
    vevent.add("organizer", organiser, encode=0)
    for guest in guests:
        attendee = vCalAddress(f"mailto:{guest.email}")
        if guest.name:
            attendee.params["CN"] = vText(guest.name)
        attendee.params["ROLE"] = vText("REQ-PARTICIPANT")
        attendee.params["PARTSTAT"] = vText(guest.status.upper())
        attendee.params["RSVP"] = vText("TRUE")
        vevent.add("attendee", attendee, encode=0)
    return vevent


def calendar_text_for(event, guests, method):
    """The iCalendar text sent to the guests: a request, or a
    cancellation."""
    calendar = Calendar()
    calendar.add("prodid", PRODID)
    calendar.add("version", "2.0")
    calendar.add("method", method)
    calendar.add_component(_vevent(event, guests, method))
    return calendar.to_ical().decode()


def _when(event):
    shown = event.in_zone(event.time_zone)
    when = shown.date.strftime("%A, %B %-d, %Y")
    if shown.end_date:
        when += shown.end_date.strftime(" to %A, %B %-d, %Y")
    if shown.start_time:
        when += " at " + shown.start_time.strftime("%-I:%M %p")
        if shown.end_time:
            when += " – " + shown.end_time.strftime("%-I:%M %p")
        when += f" ({event.time_zone})"
    return when


def _send(event, guests, method, subject, intro):
    """Email each guest the calendar text, as the alternative part a mail
    client reads as an invitation and as an attachment. Sent from the
    site's address in the user's name, with replies to the organiser
    address. Returns how many were sent; a failure is logged."""
    text = calendar_text_for(event, guests, method)
    sender = formataddr(
        (
            f"{organiser_name(event.user)} ({settings.SITE_NAME})",
            parseaddr(settings.DEFAULT_FROM_EMAIL)[1],
        )
    )
    lines = [intro, "", event.description or "Untitled", _when(event)]
    if event.location:
        lines.append(event.location)
    lines += ["", f"-- {organiser_name(event.user)}, via {settings.SITE_NAME}"]
    sent = 0
    for guest in guests:
        message = EmailMultiAlternatives(
            subject,
            "\n".join(lines),
            sender,
            [guest.email],
            reply_to=[organiser_address(event.user)],
        )
        message.attach_alternative(text, f"text/calendar; method={method}")
        message.attach("invite.ics", text, "application/ics")
        try:
            message.send(fail_silently=False)
            sent += 1
        except Exception:
            logger.exception("Could not send the invitation to %s", guest.email)
    return sent


def send_invitation(event, guests):
    """Invite the guests (the full guest list goes in the calendar text,
    so each sees who else is asked)."""
    _ensure_uid(event)
    return _send(
        event,
        guests,
        "REQUEST",
        f"Invitation: {event.description or 'Untitled'}",
        f"{organiser_name(event.user)} has invited you to:",
    )


def send_update(event):
    """The event changed: raise the revision, forget the answers, and send
    it to every guest again. Returns how many were sent."""
    guests = list(event.guests.all())
    if not guests:
        return 0
    _ensure_uid(event)
    event.invite_sequence += 1
    event.save(update_fields=["invite_sequence"])
    event.guests.update(status="needs-action", responded_at=None)
    for guest in guests:
        guest.status = "needs-action"
    return _send(
        event,
        guests,
        "REQUEST",
        f"Updated invitation: {event.description or 'Untitled'}",
        f"{organiser_name(event.user)} has changed this event:",
    )


def send_cancellation(event, guests):
    """Tell the guests the event is off, or that they are no longer asked
    to it."""
    if not guests or not event.invite_uid:
        return 0
    event.invite_sequence += 1
    event.save(update_fields=["invite_sequence"])
    return _send(
        event,
        guests,
        "CANCEL",
        f"Cancelled: {event.description or 'Untitled'}",
        f"{organiser_name(event.user)} has cancelled this event:",
    )


def after_change(event, before):
    """After an event is saved: if what its guests were told has changed,
    send the invitation again."""
    if before != details(event) and event.guests.exists():
        send_update(event)


# --- a guest's answer -------------------------------------------------------


@dataclass
class Reply:
    uid: str
    email: str
    status: str
    sequence: int


def read_reply(text):
    """A guest's answer in iCalendar text (METHOD:REPLY, with the guest as
    the attendee and their answer as its PARTSTAT), or None for text that
    is not one."""
    calendar = Calendar.from_ical(text)
    if str(calendar.get("METHOD", "")).upper() != "REPLY":
        return None
    for vevent in calendar.walk("VEVENT"):
        attendees = vevent.get("ATTENDEE")
        if attendees is None:
            continue
        if not isinstance(attendees, list):
            attendees = [attendees]
        for attendee in attendees:
            email = str(attendee).lower().removeprefix("mailto:")
            status = str(attendee.params.get("PARTSTAT", "NEEDS-ACTION")).lower()
            return Reply(
                uid=str(vevent.get("UID", "")).strip(),
                email=email,
                status=status,
                sequence=int(vevent.get("SEQUENCE", 0) or 0),
            )
    return None


def record_reply(user, reply):
    """Put a guest's answer on the guest. Returns (outcome, guest):
    'answered' with the guest; 'missing' when the event is not here,
    'unknown' when the address is not a guest of it, 'stale' for an
    answer to an older revision than the one sent."""
    event = None
    if reply.uid:
        event = Event.objects.filter(user=user, invite_uid=reply.uid).first()
    if event is None:
        return "missing", None
    guest = event.guests.filter(email__iexact=reply.email).first()
    if guest is None:
        return "unknown", None
    if reply.sequence < event.invite_sequence:
        return "stale", guest
    guest.status = reply.status if reply.status in ANSWERS else "needs-action"
    guest.responded_at = timezone.now()
    guest.save(update_fields=["status", "responded_at"])
    return "answered", guest


def answer_words(guest):
    return {
        "accepted": "accepted",
        "declined": "declined",
        "tentative": "replied maybe to",
    }.get(guest.status, "has not answered")


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
