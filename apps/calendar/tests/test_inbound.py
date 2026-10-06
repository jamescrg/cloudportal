"""The webhook Mailgun posts forwarded mail to: it takes only signed posts
to a user's own address from a sender they allow, posts the attached
invitation, and writes the user a note either way."""

import hashlib
import hmac

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.calendar.models import Event
from apps.calendar.tests.test_invitations import TIMED, ics

pytestmark = pytest.mark.django_db

KEY = "signing-key"


@pytest.fixture(autouse=True)
def inbound(settings, user):
    settings.CALENDAR_INBOUND_DOMAIN = "in.example.com"
    settings.MAILGUN_WEBHOOK_SIGNING_KEY = KEY
    user.calendar_inbound_token = "abc"
    user.save()


def _signed(**fields):
    timestamp, token = "1700000000", "tok"
    signature = hmac.new(
        KEY.encode(), f"{timestamp}{token}".encode(), hashlib.sha256
    ).hexdigest()
    return {
        "timestamp": timestamp,
        "token": token,
        "signature": signature,
        "recipient": "calendar-abc@in.example.com",
        "from": "Ollie <ollie@gmail.com>",
        "subject": "Fwd: Invitation: Dinner",
    } | fields


def _attachment(text=TIMED):
    return SimpleUploadedFile("invite.ics", text.encode(), content_type="text/calendar")


def _post(client, data):
    return client.post(reverse("calendar:inbound"), data)


def test_a_forwarded_invitation_is_posted(client, user, mailoutbox):
    response = _post(client, _signed(**{"attachment-1": _attachment()}))

    assert response.status_code == 200
    event = Event.objects.get(user=user, ical_uid="abc123@google.com")
    assert event.description == "Dinner with the Smiths"
    assert mailoutbox[0].subject == "Calendar: invitation posted"
    assert "Dinner with the Smiths on Mon, Mar 4 at 9:00 AM" in mailoutbox[0].body


def test_the_webhook_needs_no_login_or_csrf_token(user):
    from django.test import Client

    response = Client(enforce_csrf_checks=True).post(
        reverse("calendar:inbound"), _signed(**{"attachment-1": _attachment()})
    )

    assert response.status_code == 200


def test_an_unsigned_post_is_refused(client, user):
    data = _signed(**{"attachment-1": _attachment()}) | {"signature": "nope"}

    assert _post(client, data).status_code == 403
    assert not Event.objects.exists()


def test_without_a_signing_key_every_post_is_refused(client, settings):
    settings.MAILGUN_WEBHOOK_SIGNING_KEY = ""

    assert _post(client, _signed(**{"attachment-1": _attachment()})).status_code == 403


def test_an_unknown_address_is_dropped(client, mailoutbox):
    data = _signed(
        recipient="calendar-zzz@in.example.com", **{"attachment-1": _attachment()}
    )

    assert _post(client, data).status_code == 406
    assert not Event.objects.exists()
    assert mailoutbox == []


def test_a_sender_not_allowed_is_dropped(client, mailoutbox):
    data = _signed(**{"from": "stranger@example.com", "attachment-1": _attachment()})

    assert _post(client, data).status_code == 406
    assert not Event.objects.exists()
    assert mailoutbox == []


def test_a_listed_sender_is_allowed(client, user):
    user.calendar_forward_from = "me@proton.me"
    user.save()
    data = _signed(**{"from": "Me <me@proton.me>", "attachment-1": _attachment()})

    assert _post(client, data).status_code == 200
    assert Event.objects.exists()


def test_a_forward_with_no_attachment_gets_a_note_back(client, mailoutbox):
    response = _post(client, _signed(**{"body-plain": "FYI, dinner on the 4th"}))

    assert response.status_code == 406
    assert not Event.objects.exists()
    assert mailoutbox[0].subject == "Calendar: invitation not posted"
    assert "Fwd: Invitation: Dinner" in mailoutbox[0].body


def test_an_invitation_pasted_in_the_body_is_read(client):
    response = _post(client, _signed(**{"body-plain": "See below\n\n" + TIMED}))

    assert response.status_code == 200
    assert Event.objects.exists()


def test_an_attachment_named_ics_counts_whatever_its_type(client):
    upload = SimpleUploadedFile(
        "invite.ICS", TIMED.encode(), content_type="application/octet-stream"
    )

    assert _post(client, _signed(**{"attachment-1": upload})).status_code == 200


def test_a_forwarded_update_and_cancellation_follow(client, user, mailoutbox):
    _post(client, _signed(**{"attachment-1": _attachment()}))

    update = ics("DTSTART:20300305T140000Z\r\nSEQUENCE:1\r\nSUMMARY:Dinner, moved")
    _post(client, _signed(**{"attachment-1": _attachment(update)}))
    event = Event.objects.get(user=user)
    assert str(event.date) == "2030-03-05"
    assert mailoutbox[-1].subject == "Calendar: invitation updated"

    cancel = ics(
        "DTSTART:20300305T140000Z\r\nSEQUENCE:2\r\nSUMMARY:Dinner", method="CANCEL"
    )
    _post(client, _signed(**{"attachment-1": _attachment(cancel)}))
    assert not Event.objects.exists()
    assert mailoutbox[-1].subject == "Calendar: invitation cancelled"


def test_an_unreadable_attachment_gets_a_note_back(client, mailoutbox):
    upload = SimpleUploadedFile(
        "invite.ics",
        b"BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nDTSTART:soon",
        content_type="text/calendar",
    )

    assert _post(client, _signed(**{"attachment-1": upload})).status_code == 406
    assert mailoutbox[0].subject == "Calendar: invitation not posted"


def test_only_post_is_accepted(client):
    assert client.get(reverse("calendar:inbound")).status_code == 405
