"""The Filter Events dialog and the list's sort buttons.

The list opens on upcoming events; the calendar grid shows whatever month
it is on, so it applies the rest of the filter but not the period. Restore
Defaults puts both back where they started.
"""

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.calendar.models import Event

pytestmark = pytest.mark.django_db


@pytest.fixture
def events(user):
    today = timezone.localdate()
    return {
        "past": Event.objects.create(
            user=user, date=today - timedelta(days=7), description="Last week"
        ),
        "today": Event.objects.create(user=user, date=today, description="Today"),
        "future": Event.objects.create(
            user=user, date=today + timedelta(days=7), description="Next week"
        ),
    }


def _list(client):
    client.post(reverse("calendar:view-mode", args=["list"]))
    return client.get(reverse("calendar:list"))


def _feed(client):
    today = timezone.localdate()
    params = {
        "start": str(today - timedelta(days=30)),
        "end": str(today + timedelta(days=30)),
    }
    return {row["id"] for row in client.get(reverse("calendar:api"), params).json()}


def test_the_list_opens_on_upcoming_events(client, events):
    response = _list(client)

    assert list(response.context["objects"]) == [events["today"], events["future"]]
    assert response.context["filter_active"] is False


def test_the_grid_shows_past_events_too(client, events):
    assert _feed(client) == {str(e.id) for e in events.values()}


def test_period_all_and_past(client, events):
    client.post(reverse("calendar:filter"), {"period": "", "order_by": "date"})
    assert list(_list(client).context["objects"]) == [
        events["past"],
        events["today"],
        events["future"],
    ]

    client.post(reverse("calendar:filter"), {"period": "past", "order_by": "date"})
    assert list(_list(client).context["objects"]) == [events["past"]]


def test_a_date_range_filters_both_views(client, events):
    today = timezone.localdate()
    client.post(
        reverse("calendar:filter"),
        {"period": "", "date_min": str(today + timedelta(days=1)), "date_max": ""},
    )

    assert list(_list(client).context["objects"]) == [events["future"]]
    assert _feed(client) == {str(events["future"].id)}


def test_restore_defaults_means_upcoming_again(client, events):
    client.post(reverse("calendar:filter"), {"period": "past"})
    assert list(_list(client).context["objects"]) == [events["past"]]

    response = client.post(reverse("calendar:filter-default"))

    assert response.status_code == 204
    assert list(_list(client).context["objects"]) == [events["today"], events["future"]]
    assert _list(client).context["filter_active"] is False


def test_sort_buttons_toggle_direction(client, events):
    client.post(reverse("calendar:filter"), {"period": ""})

    client.post(reverse("calendar:filter-sort", args=["description"]))
    response = _list(client)
    assert [e.description for e in response.context["objects"]] == [
        "Last week",
        "Next week",
        "Today",
    ]
    assert response.context["current_order"] == "description"

    client.post(reverse("calendar:filter-sort", args=["description"]))
    assert [e.description for e in _list(client).context["objects"]] == [
        "Today",
        "Next week",
        "Last week",
    ]


def test_a_days_events_are_in_time_order(client, user):
    today = timezone.localdate()
    later = Event.objects.create(
        user=user, date=today, start_time="14:00", description="Later"
    )
    earlier = Event.objects.create(
        user=user, date=today, start_time="09:00", description="Earlier"
    )

    assert list(_list(client).context["objects"]) == [earlier, later]


def test_the_filter_dialog_shows_the_filter_as_it_stands(client):
    client.post(reverse("calendar:filter"), {"period": "past", "order_by": "-date"})

    response = client.get(reverse("calendar:filter"))

    assert response.context["filter_data"]["period"] == "past"
    assert response.context["sort_value"] == "-date"
    assert 'value="past" selected' in response.content.decode()
