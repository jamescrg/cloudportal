"""An event deleted on Google.

The deletion removes the event here only when nothing is held that Google
did not have: no edits waiting to be pushed. An event with unpushed edits
stays. It is cut loose from Google instead, and nothing sends it back there
as a new event.
"""

from datetime import date

import pytest

import apps.calendar.google as google
import apps.calendar.sync as sync
from apps.calendar.models import Event

pytestmark = pytest.mark.django_db


class FakeGoogle:
    """Stands in for the Calendar API client; keeps what was sent."""

    def __init__(self):
        self.sent = []

    def events(self):
        return self

    def insert(self, calendarId, body):
        self.sent.append(body)
        return self

    def update(self, calendarId, eventId, body):
        self.sent.append(body)
        return self

    def execute(self):
        return {"id": "google-1"}


@pytest.fixture
def remote(monkeypatch, user):
    fake = FakeGoogle()
    user.google_credentials = '{"token": "x"}'
    user.calendar_sync = True
    user.save()
    monkeypatch.setattr(google, "build_service", lambda user: fake)
    return fake


def _synced(user, remote):
    """An event on Google and in step with it."""
    event = Event.objects.create(
        user=user, date=date(2030, 3, 4), description="Dentist"
    )
    assert sync.push_event(event) == "ok"
    event.refresh_from_db()
    remote.sent.clear()
    return event


def _delete_on_google(user):
    return google._process_google_event(user, {"id": "google-1", "status": "cancelled"})


def _detached(event):
    event.refresh_from_db()
    return event.google_id is None and event.detached_from_google


def test_event_in_step_is_deleted(remote, user):
    event = _synced(user, remote)

    assert _delete_on_google(user) == "deleted"
    assert not Event.objects.filter(pk=event.pk).exists()


def test_event_with_unpushed_edits_is_kept_and_detached(remote, user):
    event = _synced(user, remote)
    event.description = "Dentist, moved to 4pm"
    event.save()

    assert _delete_on_google(user) == "detached"

    assert _detached(event)
    assert event.description == "Dentist, moved to 4pm"


def test_detaching_leaves_the_edit_time_alone(remote, user):
    event = _synced(user, remote)
    event.description = "Dentist, moved to 4pm"
    event.save()
    edited = Event.objects.get(pk=event.pk).updated_at

    _delete_on_google(user)

    event.refresh_from_db()
    assert event.updated_at == edited


def test_detached_event_is_not_pushed_back_by_the_next_sync(remote, user):
    event = _synced(user, remote)
    event.description = "Dentist, moved to 4pm"
    event.save()
    _delete_on_google(user)

    summary = sync.reconcile(user)

    assert summary == {"pushed": 0, "deleted": 0, "failed": 0}
    assert remote.sent == []
    assert _detached(event)


def test_detached_event_is_not_pushed_when_edited_later(remote, user):
    event = _synced(user, remote)
    event.description = "Dentist, moved to 4pm"
    event.save()
    _delete_on_google(user)
    event.refresh_from_db()

    event.description = "Dentist, moved again"
    event.save()

    assert sync.push_event(event) == "skipped"
    assert sync.reconcile(user)["pushed"] == 0
    assert remote.sent == []
    assert _detached(event)


def test_detached_event_is_not_matched_again(remote, user):
    event = _synced(user, remote)
    event.description = "Dentist, moved to 4pm"
    event.save()
    _delete_on_google(user)

    assert _delete_on_google(user) == "skipped"
    assert Event.objects.filter(pk=event.pk).exists()


def test_a_deletion_of_an_unknown_event_is_skipped(remote, user):
    assert _delete_on_google(user) == "skipped"


def test_another_users_event_is_not_deleted(remote, user, other_user):
    theirs = Event.objects.create(
        user=other_user,
        date=date(2030, 3, 4),
        description="Theirs",
        google_id="google-1",
    )

    assert _delete_on_google(user) == "skipped"
    assert Event.objects.filter(pk=theirs.pk).exists()


def test_event_never_pushed_is_still_pushed(remote, user):
    """The detached state must not catch an event that is only new."""
    event = Event.objects.create(user=user, date=date(2030, 3, 4), description="New")

    assert not event.detached_from_google
    assert sync.reconcile(user)["pushed"] == 1
    assert len(remote.sent) == 1
