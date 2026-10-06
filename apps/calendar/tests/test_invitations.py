"""Reading a forwarded invitation and posting it: Google's attachment
format, local times, spans, updates by revision, and cancellations."""

from datetime import date, time

import pytest

import apps.calendar.invitations as invitations
from apps.calendar.models import Event

pytestmark = pytest.mark.django_db


def ics(body, method="REQUEST"):
    return (
        "BEGIN:VCALENDAR\r\nPRODID:-//Google Inc//Google Calendar//EN\r\n"
        f"VERSION:2.0\r\nMETHOD:{method}\r\nBEGIN:VEVENT\r\n{body}\r\n"
        "DTSTAMP:20260101T000000Z\r\nORGANIZER;CN=Wife:mailto:wife@example.com\r\n"
        "UID:abc123@google.com\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
    )


TIMED = ics(
    "DTSTART:20300304T140000Z\r\nDTEND:20300304T150000Z\r\nSEQUENCE:0\r\n"
    "STATUS:CONFIRMED\r\nSUMMARY:Dinner with the Smiths\r\nLOCATION:123 Main St"
)


# --- reading ---------------------------------------------------------------


def test_a_timed_invitation_is_read_in_local_time():
    invitation = invitations.parse_invitation(TIMED)

    assert invitation.uid == "abc123@google.com"
    assert invitation.sequence == 0
    assert invitation.cancelled is False
    assert invitation.summary == "Dinner with the Smiths"
    assert invitation.location == "123 Main St"
    # 14:00Z on a March day before the clocks change is 9:00 AM Eastern
    assert invitation.date == date(2030, 3, 4)
    assert invitation.start_time == time(9, 0)
    assert invitation.end_time == time(10, 0)
    assert invitation.end_date is None


def test_an_invitation_with_a_zone_name_is_read_in_local_time():
    invitation = invitations.parse_invitation(
        ics(
            "DTSTART;TZID=America/Los_Angeles:20300304T090000\r\n"
            "DTEND;TZID=America/Los_Angeles:20300304T100000\r\nSUMMARY:Call"
        )
    )

    assert invitation.start_time == time(12, 0)
    assert invitation.end_time == time(13, 0)


def test_an_all_day_invitation():
    invitation = invitations.parse_invitation(
        ics(
            "DTSTART;VALUE=DATE:20300304\r\nDTEND;VALUE=DATE:20300305\r\nSUMMARY:Holiday"
        )
    )

    assert invitation.date == date(2030, 3, 4)
    assert invitation.start_time is None
    assert invitation.end_time is None
    assert invitation.end_date is None


def test_a_span_of_days_keeps_its_last_day():
    invitation = invitations.parse_invitation(
        ics("DTSTART;VALUE=DATE:20300304\r\nDTEND;VALUE=DATE:20300307\r\nSUMMARY:Trip")
    )

    assert invitation.end_date == date(2030, 3, 6)


def test_a_timed_span_ends_on_its_last_day():
    invitation = invitations.parse_invitation(
        ics("DTSTART:20300304T140000Z\r\nDTEND:20300306T220000Z\r\nSUMMARY:Conference")
    )

    assert invitation.date == date(2030, 3, 4)
    assert invitation.end_date == date(2030, 3, 6)
    assert invitation.end_time == time(17, 0)


def test_a_duration_stands_in_for_an_end():
    invitation = invitations.parse_invitation(
        ics("DTSTART:20300304T140000Z\r\nDURATION:PT30M\r\nSUMMARY:Call")
    )

    assert invitation.end_time == time(9, 30)


def test_a_start_with_no_end_runs_for_an_hour():
    invitation = invitations.parse_invitation(
        ics("DTSTART:20300304T140000Z\r\nSUMMARY:Call")
    )

    assert invitation.end_time == time(10, 0)


def test_a_cancellation_is_read_as_one():
    by_method = invitations.parse_invitation(
        ics("DTSTART:20300304T140000Z\r\nSUMMARY:Dinner", method="CANCEL")
    )
    by_status = invitations.parse_invitation(
        ics("DTSTART:20300304T140000Z\r\nSTATUS:CANCELLED\r\nSUMMARY:Dinner")
    )

    assert by_method.cancelled and by_status.cancelled


def test_text_with_no_event_is_nothing():
    assert (
        invitations.parse_invitation("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nEND:VCALENDAR")
        is None
    )


# --- posting ---------------------------------------------------------------


def _post(user, text):
    return invitations.post_invitation(user, invitations.parse_invitation(text))


def test_posting_creates_the_event(user):
    outcome, event = _post(user, TIMED)

    assert outcome == "created"
    assert event.user == user
    assert event.description == "Dinner with the Smiths"
    assert event.location == "123 Main St"
    assert event.ical_uid == "abc123@google.com"
    assert event.start_time == time(9, 0)


def test_a_newer_revision_updates_the_event(user):
    _, event = _post(user, TIMED)

    outcome, updated = _post(
        user,
        ics(
            "DTSTART:20300304T230000Z\r\nDTEND:20300305T000000Z\r\nSEQUENCE:1\r\n"
            "SUMMARY:Dinner with the Smiths, moved"
        ),
    )

    assert outcome == "updated"
    assert updated.pk == event.pk
    assert updated.description == "Dinner with the Smiths, moved"
    assert updated.start_time == time(18, 0)
    assert updated.location is None
    assert Event.objects.count() == 1


def test_an_older_revision_is_left_alone(user):
    _post(user, ics("DTSTART:20300304T140000Z\r\nSEQUENCE:2\r\nSUMMARY:Latest"))

    outcome, event = _post(
        user, ics("DTSTART:20300304T140000Z\r\nSEQUENCE:1\r\nSUMMARY:Earlier")
    )

    assert outcome == "stale"
    assert event.description == "Latest"


def test_a_cancellation_removes_the_event(user):
    _, event = _post(user, TIMED)

    outcome, removed = _post(
        user, ics("DTSTART:20300304T140000Z\r\nSUMMARY:Dinner", method="CANCEL")
    )

    assert outcome == "cancelled"
    assert removed.description == event.description
    assert not Event.objects.exists()


def test_a_cancellation_of_nothing_is_missing(user):
    outcome, event = _post(
        user, ics("DTSTART:20300304T140000Z\r\nSUMMARY:Dinner", method="CANCEL")
    )

    assert (outcome, event) == ("missing", None)


def test_invitations_are_matched_per_user(user, other_user):
    _post(user, TIMED)

    outcome, _ = _post(other_user, TIMED)

    assert outcome == "created"
    assert Event.objects.count() == 2


def test_a_long_title_is_cut_to_fit(user):
    _, event = _post(
        user, ics("DTSTART;VALUE=DATE:20300304\r\nSUMMARY:" + "word " * 80)
    )

    assert len(event.description) <= 255


# --- addresses -------------------------------------------------------------


def test_allowed_senders_are_the_users_own_and_the_listed_ones(user):
    user.calendar_forward_from = (
        "Me <me@proton.me>\nalso@example.com, Third@Example.com"
    )

    assert invitations.allowed_senders(user) == {
        "ollie@gmail.com",
        "me@proton.me",
        "also@example.com",
        "third@example.com",
    }


def test_the_forwarding_address_needs_a_domain_and_a_token(user, settings):
    settings.CALENDAR_INBOUND_DOMAIN = ""
    user.calendar_inbound_token = "abc"
    assert invitations.inbound_address(user) is None

    settings.CALENDAR_INBOUND_DOMAIN = "in.example.com"
    assert invitations.inbound_address(user) == "calendar-abc@in.example.com"

    user.calendar_inbound_token = None
    assert invitations.inbound_address(user) is None


def test_the_recipient_names_the_user(user, settings):
    settings.CALENDAR_INBOUND_DOMAIN = "in.example.com"
    user.calendar_inbound_token = "abc"
    user.save()

    assert invitations.user_for_recipient("Cal <CALENDAR-abc@IN.example.com>") == user
    assert invitations.user_for_recipient("calendar-abc@elsewhere.com") is None
    assert invitations.user_for_recipient("calendar-xyz@in.example.com") is None
    assert invitations.user_for_recipient("abc@in.example.com") is None
    assert invitations.user_for_recipient("calendar-@in.example.com") is None
