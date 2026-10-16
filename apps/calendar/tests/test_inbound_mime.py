"""The calendar address, one for everyone on the machine: Mailgun posts
the raw message, a guest's answer finds its event by UID, and a forwarded
invitation finds its user by a From line its mail provider has signed
(DKIM)."""

import hashlib
import hmac
from datetime import date
from email.message import EmailMessage

import dkim
import pytest
from django.urls import reverse

from apps.calendar import invitations
from apps.calendar.models import Event, EventGuest
from apps.calendar.tests.test_invitations import TIMED, ics

pytestmark = pytest.mark.django_db

KEY = "signing-key"
ADDRESS = "calendar@in.example.com"

# A key for signing test mail only, its public half served by fake DNS
DKIM_KEY = b"""-----BEGIN RSA PRIVATE KEY-----
MIICXQIBAAKBgQDrvmBL2xXzOx1t0bHfdpG/Co4Qxk0gD0crwIVua9HArJn8h5AV
MvNCOIeSNw2nt7rEMZn7kUAZ6zK/aW3kYR2sfZ7UNxiVTzybOVr1Ff6GeJ5nq9xA
axFX9z+TjUcUjVLrAUqUM2qdfmkBOsd7IU/oXjtMEiCjeHOnSGO9bBKsIQIDAQAB
AoGBAJzBOFL4WT4lHsp5VydaNkur/w9UbNBWmGKVX6Qu+Yh+vN3YXoxaFrr/z9X/
2YqedwgiW1uWF+OkK1hwCGyFzy4umYZ890PD8fVy8s3lQ9osJp6Hjfzo1sfHaPYi
O71Ab/CFh1T042zXjiQFE2foFYctsdpaAz/C1iPA7Kxbv3VpAkEA9+cOsPvqvbpC
kRW6bd5ny2677g0zhm+EbfCcDOEJjWl8xnI2VutPAlRzan+dJ4gUsBEm13gVfnvS
epX/qmEVTwJBAPNxpZlMtC8KwZ4zM31KOFAbCRktl5v3UgyKfXsNtHSDnpSP0Dys
OYrIyW7QYqAde1UBvXxfiRyg3IFKl0Ckq48CQQDBeG8ryv9xoMrQxh9gHaHtz3cV
mvHqal/1GUIAfyRgW8JIcdxcy3o2/EezBvNUZcyXeFtS7+H+e45Ro30LsIbbAkBp
2P0GlYo2dffPYDXAARhRBCBFmUQ1JSjAmSqL6V6P1naJ46nH554xULH8g5COS6NH
R7VqsWM9Vlfpw1PWYILTAkAuf37+RWM5LmzNKAFg0LpESXrW6lnN9fZhAlT9FY9f
Pm3Ez3S3xE2QtmxfTZz32JEeeGtofrLu87WeTViLkcUf
-----END RSA PRIVATE KEY-----
"""
DKIM_RECORD = b"v=DKIM1; k=rsa; p=MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQDrvmBL2xXzOx1t0bHfdpG/Co4Qxk0gD0crwIVua9HArJn8h5AVMvNCOIeSNw2nt7rEMZn7kUAZ6zK/aW3kYR2sfZ7UNxiVTzybOVr1Ff6GeJ5nq9xAaxFX9z+TjUcUjVLrAUqUM2qdfmkBOsd7IU/oXjtMEiCjeHOnSGO9bBKsIQIDAQAB"


def _dns(name, timeout=5):
    return DKIM_RECORD if name.startswith(b"sel._domainkey.") else None


@pytest.fixture(autouse=True)
def inbound(settings, monkeypatch):
    settings.CALENDAR_INBOUND_DOMAIN = "in.example.com"
    settings.CALENDAR_INBOUND_ADDRESS = ADDRESS
    settings.MAILGUN_WEBHOOK_SIGNING_KEY = KEY
    real = invitations.signing_domains
    monkeypatch.setattr(
        invitations, "signing_domains", lambda raw, dnsfunc=None: real(raw, _dns)
    )


def _message(
    sender="Ollie <ollie@gmail.com>", text=TIMED, subject="Fwd: Invitation: Dinner"
):
    message = EmailMessage()
    message["From"] = sender
    message["To"] = ADDRESS
    message["Subject"] = subject
    message.set_content("Forwarded invitation.")
    if text is not None:
        message.add_attachment(
            text.encode(), maintype="text", subtype="calendar", filename="invite.ics"
        )
    return message.as_bytes(policy=message.policy.clone(linesep="\r\n"))


def _sign(raw, domain="gmail.com"):
    header = dkim.sign(
        raw,
        b"sel",
        domain.encode(),
        DKIM_KEY,
        include_headers=[b"from", b"to", b"subject"],
    )
    return header + raw


def _post(client, raw, recipient=ADDRESS, **fields):
    timestamp, token = "1700000000", "tok"
    signature = hmac.new(
        KEY.encode(), f"{timestamp}{token}".encode(), hashlib.sha256
    ).hexdigest()
    data = {
        "timestamp": timestamp,
        "token": token,
        "signature": signature,
        "recipient": recipient,
        "body-mime": raw.decode(),
    } | fields
    return client.post(reverse("calendar:inbound-mime"), data)


def test_a_signed_forward_from_the_users_address_is_posted(client, user, mailoutbox):
    response = _post(client, _sign(_message()))

    assert response.status_code == 200
    event = Event.objects.get(user=user, ical_uid="abc123@google.com")
    assert event.description == "Dinner with the Smiths"
    assert mailoutbox[0].subject == "Calendar: invitation posted"


def test_a_listed_sender_finds_its_user(client, user):
    user.calendar_forward_from = "me@proton.me"
    user.save()

    response = _post(client, _sign(_message("Me <me@proton.me>"), "proton.me"))

    assert response.status_code == 200
    assert Event.objects.filter(user=user).count() == 1


def test_an_unsigned_forward_is_refused(client, user, mailoutbox):
    response = _post(client, _message())

    assert response.status_code == 406
    assert not Event.objects.exists()
    assert not mailoutbox


def test_a_signature_from_another_domain_does_not_vouch_for_the_from_line(client, user):
    response = _post(client, _sign(_message(), "evil.example"))

    assert response.status_code == 406
    assert not Event.objects.exists()


def test_a_from_line_changed_after_signing_is_refused(client, user):
    raw = _sign(_message("Nico <nico@gmail.com>"))
    raw = raw.replace(b"From: Nico <nico@gmail.com>", b"From: Ollie <ollie@gmail.com>")

    response = _post(client, raw)

    assert response.status_code == 406
    assert not Event.objects.exists()


def test_a_second_from_line_is_refused(client, user):
    raw = _sign(_message("Nico <nico@gmail.com>"))
    raw = b"From: Ollie <ollie@gmail.com>\r\n" + raw

    assert _post(client, raw).status_code == 406
    assert not Event.objects.exists()


def test_a_subdomain_of_the_signer_is_aligned_but_not_its_parent():
    under = _sign(_message("Ollie <ollie@mail.example.org>"), "example.org")
    over = _sign(_message("Ollie <ollie@example.org>"), "mail.example.org")

    assert invitations.sender_is_signed(invitations.parse_message(under), under, _dns)
    assert not invitations.sender_is_signed(invitations.parse_message(over), over, _dns)


def test_a_sender_who_is_no_user_is_refused(client, user):
    response = _post(client, _sign(_message("Stranger <stranger@gmail.com>")))

    assert response.status_code == 406


def test_a_sender_two_users_list_is_refused(client, user, other_user):
    other_user.calendar_forward_from = "ollie@gmail.com"
    other_user.save()

    assert _post(client, _sign(_message())).status_code == 406
    assert not Event.objects.exists()


def test_mail_for_another_address_is_refused(client, user):
    raw = _sign(_message())

    response = _post(client, raw, recipient="kosmos-dev-calendar@in.example.com")

    assert response.status_code == 406
    assert not Event.objects.exists()


def test_an_unsigned_post_is_refused(client, user):
    response = _post(client, _sign(_message()), signature="forged")

    assert response.status_code == 403


def test_a_forward_with_no_invitation_gets_a_note_back(client, user, mailoutbox):
    response = _post(client, _sign(_message(text=None)))

    assert response.status_code == 406
    assert mailoutbox[0].subject == "Calendar: invitation not posted"


def _reply(uid, email="wife@example.com"):
    return (
        "BEGIN:VCALENDAR\r\nPRODID:-//Google Inc//Google Calendar//EN\r\nVERSION:2.0\r\n"
        "METHOD:REPLY\r\nBEGIN:VEVENT\r\nDTSTART:20300305T000000Z\r\n"
        f"DTSTAMP:20300101T000000Z\r\nUID:{uid}\r\n"
        f"ATTENDEE;PARTSTAT=ACCEPTED;CN=Katie:mailto:{email}\r\n"
        "SEQUENCE:0\r\nSUMMARY:Accepted: Dinner\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
    )


def test_a_guests_answer_finds_its_event_by_uid(client, user, other_user, mailoutbox):
    Event.objects.create(user=other_user, date=date(2030, 3, 4), description="Theirs")
    event = Event.objects.create(
        user=user, date=date(2030, 3, 4), description="Dinner", invite_uid="u-1@in"
    )
    EventGuest.objects.create(event=event, email="wife@example.com", name="Katie")

    # unsigned, from the guest: an answer needs only the UID and the guest
    raw = _message("Katie <wife@example.com>", text=_reply("u-1@in"))
    response = _post(client, raw)

    assert response.status_code == 200
    assert event.guests.get().status == "accepted"
    assert mailoutbox[-1].to == ["ollie@gmail.com"]


def test_an_answer_from_someone_not_a_guest_is_refused(client, user):
    event = Event.objects.create(
        user=user, date=date(2030, 3, 4), description="Dinner", invite_uid="u-1@in"
    )
    EventGuest.objects.create(event=event, email="wife@example.com")

    raw = _message(text=_reply("u-1@in", email="stranger@example.com"))

    assert _post(client, raw).status_code == 406
    assert event.guests.get().status == "needs-action"


def test_an_answer_to_an_unknown_invitation_is_refused(client, user):
    assert _post(client, _message(text=_reply("nothing@in"))).status_code == 406


def test_invitations_name_the_calendar_address_as_organiser(user):
    assert invitations.organiser_address(user) == ADDRESS


def test_the_settings_card_shows_the_calendar_address(client, user):
    user.calendar_inbound_token = "abc"
    user.save()

    html = client.get(reverse("settings-calendar")).content.decode()

    assert ADDRESS in html
    assert "calendar-abc@in.example.com" in html and "Retire" in html


def test_a_pasted_invitation_is_read_from_the_raw_message():
    message = EmailMessage()
    message.set_content("See below\n" + ics("SUMMARY:x"))

    assert "SUMMARY:x" in invitations.message_calendar_text(message)
