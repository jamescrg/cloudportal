"""What a pull from Google writes into an event: a title too long for the
description column is cut to fit, and a location removed on Google is
removed here. Local edits not yet pushed are never overwritten."""

from datetime import date

import pytest

import apps.calendar.google as google
from apps.calendar.models import Event, PendingGoogleDeletion

pytestmark = pytest.mark.django_db

DAY = {"start": {"date": "2030-03-04"}, "end": {"date": "2030-03-05"}}
LIMIT = Event._meta.get_field("description").max_length


def _in_step(user, **fields):
    """An event held here that matches what Google has."""
    event = Event.objects.create(
        user=user,
        date=date(2030, 3, 4),
        description="Dentist",
        google_id="google-1",
        **fields,
    )
    Event.objects.filter(pk=event.pk).update(google_synced_at=event.updated_at)
    event.refresh_from_db()
    return event


def _pull(user, **google_fields):
    return google._process_google_event(user, {"id": "google-1"} | DAY | google_fields)


# --- new events ------------------------------------------------------------


def test_a_new_google_event_is_created_for_the_user(user):
    assert _pull(user, summary="Dentist") == "created"

    event = Event.objects.get(google_id="google-1")
    assert event.user == user
    assert event.description == "Dentist"
    assert event.google_synced_at == event.updated_at


def test_an_untitled_google_event_gets_a_description(user):
    _pull(user)

    assert Event.objects.get(google_id="google-1").description == "Untitled"


def test_an_event_queued_for_deletion_is_not_recreated(user):
    PendingGoogleDeletion.objects.create(user=user, google_id="google-1")

    assert _pull(user, summary="Dentist") == "skipped"
    assert not Event.objects.exists()


# --- long titles -----------------------------------------------------------


def test_long_title_is_cut_on_a_word_boundary(user):
    title = " ".join(["appointment"] * 40)
    assert len(title) > LIMIT

    assert _pull(user, summary=title) == "created"

    description = Event.objects.get(google_id="google-1").description
    assert len(description) <= LIMIT
    assert title.startswith(description)
    assert description.endswith("appointment")


def test_long_title_with_no_spaces_is_cut_at_the_limit(user):
    _pull(user, summary="x" * 400)

    assert Event.objects.get(google_id="google-1").description == "x" * LIMIT


# --- updates ---------------------------------------------------------------


def test_a_changed_title_is_taken(user):
    event = _in_step(user)

    assert _pull(user, summary="Dentist, rescheduled") == "updated"

    event.refresh_from_db()
    assert event.description == "Dentist, rescheduled"
    assert event.google_synced_at == event.updated_at


def test_location_removed_on_google_is_cleared(user):
    event = _in_step(user, location="100 Main St")

    _pull(user, summary="Dentist")

    event.refresh_from_db()
    assert event.location is None


def test_unpushed_local_edits_are_kept(user):
    event = _in_step(user)
    event.location = "100 Main St"
    event.save()

    assert _pull(user, summary="Dentist, rescheduled") == "skipped"

    event.refresh_from_db()
    assert event.location == "100 Main St"
    assert event.description == "Dentist"


def test_removing_the_location_on_google_removes_it_here(user):
    event = _in_step(user, location="https://zoom.example/j/1")

    _pull(user, summary="Dentist")

    event.refresh_from_db()
    assert event.location is None


def test_another_users_event_with_the_same_id_is_not_touched(user, other_user):
    theirs = _in_step(other_user)

    assert _pull(user, summary="Mine") == "created"

    theirs.refresh_from_db()
    assert theirs.description == "Dentist"
    assert Event.objects.filter(google_id="google-1").count() == 2
