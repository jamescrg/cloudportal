"""An event deleted on Google and kept here says so on screen: on the list
row and above the Edit Event form."""

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.calendar.models import Event

pytestmark = pytest.mark.django_db

NOTE = "Not on Google Calendar"


@pytest.fixture
def detached(user):
    return Event.objects.create(
        user=user,
        date="2030-01-01",
        description="Kept after Google deletion",
        google_id=None,
        google_synced_at=timezone.now(),
    )


@pytest.fixture
def never_pushed(user):
    return Event.objects.create(
        user=user, date="2030-01-02", description="Never on Google"
    )


def test_the_list_marks_a_detached_event(client, detached, never_pushed):
    client.post(reverse("calendar:view-mode", args=["list"]))
    html = client.get(reverse("calendar:list")).content.decode()
    assert html.count(NOTE) == 1
    assert html.index("Kept after Google deletion") < html.index(NOTE)


def test_the_edit_form_says_it(client, detached, never_pushed):
    assert (
        NOTE
        in client.get(reverse("calendar:edit", args=[detached.id])).content.decode()
    )
    assert (
        NOTE
        not in client.get(
            reverse("calendar:edit", args=[never_pushed.id])
        ).content.decode()
    )
