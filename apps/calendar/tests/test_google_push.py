"""What a save sends to Google, and how the sync recovers when it can't."""

from datetime import date, time

import pytest

import apps.calendar.google as google
import apps.calendar.sync as sync
from apps.calendar.models import Event, PendingGoogleDeletion

pytestmark = pytest.mark.django_db


class FakeGoogle:
    """Stands in for the Calendar API client; keeps what was sent."""

    def __init__(self):
        self.sent = []
        self.deleted = []
        self.fail = False

    def events(self):
        return self

    def insert(self, calendarId, body):
        self.sent.append(("insert", body))
        return self

    def update(self, calendarId, eventId, body):
        self.sent.append(("update", eventId, body))
        return self

    def delete(self, calendarId, eventId):
        self.deleted.append(eventId)
        return self

    def execute(self):
        if self.fail:
            raise RuntimeError("Google is down")
        return {"id": "google-1"}


@pytest.fixture
def remote(monkeypatch, user):
    fake = FakeGoogle()
    user.google_credentials = '{"token": "x"}'
    user.calendar_sync = True
    user.save()
    monkeypatch.setattr(google, "build_service", lambda user: fake)
    return fake


def test_not_connected_means_no_push(user):
    event = Event.objects.create(user=user, date=date(2030, 3, 4), description="Call")

    assert sync.push_event(event) == "skipped"
    event.refresh_from_db()
    assert event.google_id is None
    assert event.google_synced_at is None


def test_sync_turned_off_means_no_push_even_when_connected(remote, user):
    user.calendar_sync = False
    user.save()
    event = Event.objects.create(user=user, date=date(2030, 3, 4), description="Call")

    assert sync.push_event(event) == "skipped"
    assert sync.reconcile(user) == {"pushed": 0, "deleted": 0, "failed": 0}
    assert remote.sent == []


def test_first_push_creates_and_marks_synced(remote, user):
    event = Event.objects.create(
        user=user,
        date=date(2030, 3, 4),
        start_time=time(9, 0),
        end_time=time(10, 0),
        description="Call",
        location="Zoom",
    )

    assert sync.push_event(event) == "ok"

    kind, body = remote.sent[0]
    assert kind == "insert"
    assert body["summary"] == "Call"
    assert body["start"]["dateTime"] == "2030-03-04T09:00:00"
    assert body["end"]["dateTime"] == "2030-03-04T10:00:00"
    assert body["location"] == "Zoom"

    event.refresh_from_db()
    assert event.google_id == "google-1"
    assert event.google_synced_at == event.updated_at


def test_all_day_event_is_sent_as_a_date(remote, user):
    event = Event.objects.create(
        user=user, date=date(2030, 3, 4), description="Holiday"
    )

    sync.push_event(event)

    _, body = remote.sent[0]
    assert body["start"] == {"date": "2030-03-04"}
    assert body["end"] == {"date": "2030-03-05"}


def test_second_push_updates(remote, user):
    event = Event.objects.create(user=user, date=date(2030, 3, 4), description="Call")
    sync.push_event(event)
    event.refresh_from_db()
    event.description = "Call, moved"
    event.save()

    assert sync.push_event(event) == "ok"

    kind, google_id, body = remote.sent[1]
    assert kind == "update"
    assert google_id == "google-1"
    assert body["summary"] == "Call, moved"


def test_failed_push_is_left_for_reconcile(remote, user):
    event = Event.objects.create(user=user, date=date(2030, 3, 4), description="Call")
    remote.fail = True

    assert sync.push_event(event) == "failed"
    event.refresh_from_db()
    assert event.google_synced_at is None

    remote.fail = False
    assert sync.reconcile(user) == {"pushed": 1, "deleted": 0, "failed": 0}
    event.refresh_from_db()
    assert event.google_id == "google-1"


def test_reconcile_pushes_only_what_changed(remote, user):
    synced = Event.objects.create(user=user, date=date(2030, 3, 4), description="Old")
    sync.push_event(synced)
    Event.objects.create(user=user, date=date(2030, 3, 5), description="New")
    remote.sent.clear()

    assert sync.reconcile(user)["pushed"] == 1
    assert remote.sent[0][1]["summary"] == "New"


def test_reconcile_is_per_user(remote, user, other_user):
    Event.objects.create(user=other_user, date=date(2030, 3, 5), description="Theirs")

    assert sync.reconcile(user)["pushed"] == 0
    assert remote.sent == []


def test_delete_removes_from_google(remote, user):
    event = Event.objects.create(user=user, date=date(2030, 3, 4), description="Call")
    sync.push_event(event)
    event.refresh_from_db()

    assert sync.delete_event_remote(event) == "ok"
    assert remote.deleted == ["google-1"]


def test_failed_delete_is_queued_and_drained(remote, user):
    event = Event.objects.create(user=user, date=date(2030, 3, 4), description="Call")
    sync.push_event(event)
    event.refresh_from_db()
    remote.fail = True

    assert sync.delete_event_remote(event) == "failed"
    assert PendingGoogleDeletion.objects.filter(
        user=user, google_id="google-1"
    ).exists()

    remote.fail = False
    assert sync.reconcile(user)["deleted"] == 1
    assert not PendingGoogleDeletion.objects.exists()


def test_delete_while_disconnected_is_queued(user):
    event = Event.objects.create(
        user=user, date=date(2030, 3, 4), description="Call", google_id="google-9"
    )

    assert sync.delete_event_remote(event) == "queued"
    assert PendingGoogleDeletion.objects.filter(google_id="google-9").exists()


def test_the_view_saves_locally_when_google_fails(remote, client):
    remote.fail = True

    response = client.post(
        "/calendar/add", {"date": "2030-03-04", "description": "Call"}
    )

    assert response.status_code == 204
    event = Event.objects.get(description="Call")
    assert event.google_id is None
