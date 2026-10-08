"""Inviting guests to an event: the invitation emailed, sent again when
the event changes, cancelled when a guest is removed or the event
deleted, and a guest's answer read back through the webhook."""

import hashlib
import hmac
from datetime import date, time

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.calendar import invitations
from apps.calendar.models import Event, EventGuest

pytestmark = pytest.mark.django_db

KEY = "signing-key"


@pytest.fixture(autouse=True)
def organiser(settings, user):
    settings.CALENDAR_INBOUND_DOMAIN = "in.example.com"
    settings.MAILGUN_WEBHOOK_SIGNING_KEY = KEY
    settings.DEFAULT_FROM_EMAIL = "Cloud Portal <no-reply@example.com>"
    settings.SITE_NAME = "Cloud Portal"
    user.calendar_inbound_token = "abc"
    user.first_name, user.last_name = "Ollie", "Craig"
    user.time_zone = "America/New_York"
    user.save()


@pytest.fixture
def dinner(user):
    return Event.objects.create(
        user=user,
        date=date(2030, 3, 4),
        start_time=time(19, 0),
        end_time=time(21, 0),
        description="Dinner",
        location="Home",
        time_zone="America/New_York",
    )


def _invite(client, event, email="wife@example.com", name=""):
    return client.post(
        reverse("calendar:guest-add", args=[event.id]), {"email": email, "name": name}
    )


def _calendar_part(message):
    """The invitation in the mail, its long lines unfolded."""
    text = next(
        c for c, kind in message.alternatives if kind.startswith("text/calendar")
    )
    return text.replace("\r\n ", "")


# --- inviting ----------------------------------------------------------------


def test_inviting_a_guest_emails_an_invitation(client, dinner, mailoutbox):
    response = _invite(client, dinner, name="Katie")

    assert response.status_code == 200
    assert (
        "Katie" in response.content.decode() and "Invited" in response.content.decode()
    )
    guest = dinner.guests.get()
    assert (guest.email, guest.name, guest.status) == (
        "wife@example.com",
        "Katie",
        "needs-action",
    )

    message = mailoutbox[0]
    assert message.to == ["wife@example.com"]
    assert message.subject == "Invitation: Dinner"
    assert message.from_email == '"Ollie Craig (Cloud Portal)" <no-reply@example.com>'
    assert message.reply_to == ["calendar-abc@in.example.com"]
    assert "Monday, March 4, 2030 at 7:00 PM – 9:00 PM" in message.body
    text = _calendar_part(message)
    assert "METHOD:REQUEST" in text
    assert 'ORGANIZER;CN="Ollie Craig":mailto:calendar-abc@in.example.com' in text
    attendee = next(line for line in text.splitlines() if line.startswith("ATTENDEE"))
    assert attendee.endswith(":mailto:wife@example.com")
    for param in (
        "CN=Katie",
        "PARTSTAT=NEEDS-ACTION",
        "ROLE=REQ-PARTICIPANT",
        "RSVP=TRUE",
    ):
        assert param in attendee

    assert "DTSTART:20300305T000000Z" in text and "DTEND:20300305T020000Z" in text
    assert "SEQUENCE:0" in text
    dinner.refresh_from_db()
    assert f"UID:{dinner.invite_uid}" in text and dinner.invite_uid.endswith(
        "@in.example.com"
    )
    assert [name for name, *_ in message.attachments] == ["invite.ics"]


def test_an_all_day_invitation_ends_the_day_after(client, user, mailoutbox):
    trip = Event.objects.create(
        user=user, date=date(2030, 3, 4), end_date=date(2030, 3, 6), description="Trip"
    )

    _invite(client, trip)

    text = _calendar_part(mailoutbox[0])
    assert "DTSTART;VALUE=DATE:20300304" in text
    assert "DTEND;VALUE=DATE:20300307" in text


def test_a_guest_is_invited_once(client, dinner, mailoutbox):
    _invite(client, dinner)
    response = _invite(client, dinner, email="Wife@Example.com")

    assert "Already invited" in response.content.decode()
    assert dinner.guests.count() == 1 and len(mailoutbox) == 1


def test_without_a_forwarding_address_no_one_can_be_invited(
    client, user, dinner, mailoutbox
):
    user.calendar_inbound_token = ""
    user.save()

    html = client.get(f"/calendar/{dinner.id}/edit").content.decode()
    assert "create your calendar address" in html
    assert 'name="email"' not in html

    assert _invite(client, dinner).status_code == 200
    assert not dinner.guests.exists() and mailoutbox == []


def test_a_guest_whose_invitation_cannot_be_sent_is_not_added(
    client, dinner, mailoutbox, monkeypatch
):
    from django.core.mail import EmailMultiAlternatives

    def down(self, *args, **kwargs):
        raise TimeoutError("timed out")

    monkeypatch.setattr(EmailMultiAlternatives, "send", down)

    response = _invite(client, dinner)

    assert "could not be emailed" in response.content.decode()
    assert not dinner.guests.exists()


def test_the_edit_form_lists_the_guests_and_their_answers(client, dinner):
    EventGuest.objects.create(
        event=dinner, email="wife@example.com", name="Katie", status="accepted"
    )
    EventGuest.objects.create(event=dinner, email="bob@example.com", status="declined")

    html = client.get(f"/calendar/{dinner.id}/edit").content.decode()

    assert "Katie" in html and "Accepted" in html
    assert "bob@example.com" in html and "Declined" in html
    assert reverse("calendar:guest-add", args=[dinner.id]) in html


# --- changes -------------------------------------------------------------------


def test_removing_a_guest_cancels_their_invitation(client, dinner, mailoutbox):
    _invite(client, dinner)
    guest = dinner.guests.get()

    response = client.post(reverse("calendar:guest-delete", args=[dinner.id, guest.id]))

    assert response.status_code == 200 and "No guests" in response.content.decode()
    assert not dinner.guests.exists()
    message = mailoutbox[-1]
    assert message.subject == "Cancelled: Dinner"
    text = _calendar_part(message)
    assert (
        "METHOD:CANCEL" in text and "STATUS:CANCELLED" in text and "SEQUENCE:1" in text
    )


def test_a_changed_event_is_sent_again_and_the_answers_forgotten(
    client, dinner, mailoutbox
):
    _invite(client, dinner)
    dinner.guests.update(status="accepted")

    client.post(
        f"/calendar/{dinner.id}/edit",
        {
            "date": "2030-03-04",
            "start_time": "20:00",
            "end_time": "21:00",
            "description": "Dinner",
            "location": "Home",
        },
    )

    assert dinner.guests.get().status == "needs-action"
    dinner.refresh_from_db()
    assert dinner.invite_sequence == 1
    message = mailoutbox[-1]
    assert message.subject == "Updated invitation: Dinner"
    text = _calendar_part(message)
    assert "SEQUENCE:1" in text and "DTSTART:20300305T010000Z" in text
    assert f"UID:{dinner.invite_uid}" in text


def test_an_edit_that_changes_nothing_sends_nothing(client, dinner, mailoutbox):
    _invite(client, dinner)
    dinner.guests.update(status="accepted")

    client.post(
        f"/calendar/{dinner.id}/edit",
        {
            "date": "2030-03-04",
            "start_time": "19:00",
            "end_time": "21:00",
            "description": "Dinner",
            "location": "Home",
        },
    )

    assert len(mailoutbox) == 1
    assert dinner.guests.get().status == "accepted"


def test_deleting_the_event_cancels_every_guest(client, dinner, mailoutbox):
    _invite(client, dinner, email="wife@example.com")
    _invite(client, dinner, email="bob@example.com")

    client.post(f"/calendar/{dinner.id}/delete")

    assert not Event.objects.filter(pk=dinner.pk).exists()
    cancelled = [m for m in mailoutbox if m.subject == "Cancelled: Dinner"]
    assert sorted(m.to[0] for m in cancelled) == ["bob@example.com", "wife@example.com"]


# --- the answer ------------------------------------------------------------------


def _reply(uid, status="ACCEPTED", sequence=0, email="wife@example.com"):
    return (
        "BEGIN:VCALENDAR\r\nPRODID:-//Google Inc//Google Calendar//EN\r\nVERSION:2.0\r\n"
        "METHOD:REPLY\r\nBEGIN:VEVENT\r\nDTSTART:20300305T000000Z\r\nDTEND:20300305T020000Z\r\n"
        "DTSTAMP:20300101T000000Z\r\nORGANIZER;CN=Ollie Craig:mailto:calendar-abc@in.example.com\r\n"
        f"UID:{uid}\r\nATTENDEE;CUTYPE=INDIVIDUAL;ROLE=REQ-PARTICIPANT;PARTSTAT={status};CN=Katie"
        f":mailto:{email}\r\nSEQUENCE:{sequence}\r\nSUMMARY:Accepted: Dinner\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
    )


def _signed_reply(text):
    timestamp, token = "1700000000", "tok"
    signature = hmac.new(
        KEY.encode(), f"{timestamp}{token}".encode(), hashlib.sha256
    ).hexdigest()
    return {
        "timestamp": timestamp,
        "token": token,
        "signature": signature,
        "recipient": "calendar-abc@in.example.com",
        "from": "Katie <wife@example.com>",
        "subject": "Accepted: Dinner @ Mon Mar 4, 2030",
        "attachment-1": SimpleUploadedFile(
            "invite.ics", text.encode(), content_type="text/calendar"
        ),
    }


def test_a_reply_is_read():
    reply = invitations.read_reply(_reply("uid-1", status="TENTATIVE", sequence=2))

    assert (reply.uid, reply.email, reply.status, reply.sequence) == (
        "uid-1",
        "wife@example.com",
        "tentative",
        2,
    )
    from apps.calendar.tests.test_invitations import TIMED

    assert invitations.read_reply(TIMED) is None


def test_a_guests_answer_comes_back_through_the_webhook(client, dinner, mailoutbox):
    _invite(client, dinner, name="Katie")
    dinner.refresh_from_db()

    response = client.post(
        reverse("calendar:inbound"), _signed_reply(_reply(dinner.invite_uid))
    )

    assert response.status_code == 200
    guest = dinner.guests.get()
    assert guest.status == "accepted" and guest.responded_at is not None
    note = mailoutbox[-1]
    assert note.subject == "Calendar: Katie accepted your invitation"
    assert "Katie accepted Dinner on Mon, Mar 4 at 7:00 PM" in note.body


def test_a_decline_and_a_maybe_are_recorded(client, dinner, mailoutbox):
    _invite(client, dinner)
    dinner.refresh_from_db()

    client.post(
        reverse("calendar:inbound"),
        _signed_reply(_reply(dinner.invite_uid, "DECLINED")),
    )
    assert dinner.guests.get().status == "declined"

    client.post(
        reverse("calendar:inbound"),
        _signed_reply(_reply(dinner.invite_uid, "TENTATIVE")),
    )
    assert dinner.guests.get().status == "tentative"
    assert (
        mailoutbox[-1].subject
        == "Calendar: wife@example.com replied maybe to your invitation"
    )


def test_an_answer_to_an_old_revision_is_left_alone(client, dinner, mailoutbox):
    _invite(client, dinner)
    invitations.send_update(dinner)
    dinner.refresh_from_db()

    response = client.post(
        reverse("calendar:inbound"),
        _signed_reply(_reply(dinner.invite_uid, sequence=0)),
    )

    assert response.status_code == 406
    assert dinner.guests.get().status == "needs-action"


def test_an_answer_from_no_guest_is_dropped(client, dinner):
    _invite(client, dinner)
    dinner.refresh_from_db()

    response = client.post(
        reverse("calendar:inbound"),
        _signed_reply(_reply(dinner.invite_uid, email="stranger@example.com")),
    )

    assert response.status_code == 406
    assert dinner.guests.get().status == "needs-action"


def test_an_answer_for_an_unknown_event_is_dropped(client, dinner):
    assert (
        client.post(
            reverse("calendar:inbound"), _signed_reply(_reply("nothing@in.example.com"))
        ).status_code
        == 406
    )
