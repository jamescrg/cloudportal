from datetime import date

import pytest
from django.utils import timezone

from apps.calendar.models import Event

pytestmark = pytest.mark.django_db


def test_string(event):
    assert str(event) == f"{event.description} : {event.id}"


def test_content(user, event):
    assert event.user == user
    assert event.date == date(2022, 12, 28) or event.date == "2022-12-28"
    assert event.description == "File Answer"
    assert event.start_time is None


def test_detached_means_synced_once_and_now_without_a_google_id(user):
    never_pushed = Event.objects.create(user=user, date="2030-01-01", description="New")
    on_google = Event.objects.create(
        user=user,
        date="2030-01-01",
        description="Synced",
        google_id="g-1",
        google_synced_at=timezone.now(),
    )
    detached = Event.objects.create(
        user=user,
        date="2030-01-01",
        description="Kept",
        google_synced_at=timezone.now(),
    )

    assert not never_pushed.detached_from_google
    assert not on_google.detached_from_google
    assert detached.detached_from_google
