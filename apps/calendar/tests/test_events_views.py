import pytest
from django.urls import reverse
from pytest_django.asserts import assertTemplateUsed

from apps.calendar.models import Event

pytestmark = pytest.mark.django_db


def test_index(client):
    response = client.get("/calendar/")
    assert response.status_code == 200
    assert response.context["page"] == "calendar"
    assertTemplateUsed(response, "calendar/content.html")
    assertTemplateUsed(response, "calendar/calendar.html")


def test_index_requires_login():
    from django.test import Client

    assert Client().get("/calendar/").status_code == 302


def test_list_partial_follows_the_saved_view(client):
    response = client.get(reverse("calendar:list"))
    assertTemplateUsed(response, "calendar/calendar.html")

    assert client.post(reverse("calendar:view-mode", args=["list"])).status_code == 204

    response = client.get(reverse("calendar:list"))
    assertTemplateUsed(response, "calendar/list.html")
    assert "objects" in response.context

    response = client.get("/calendar/")
    assertTemplateUsed(response, "calendar/list.html")


def test_the_calendar_partial_is_served_whatever_the_saved_view(client):
    client.post(reverse("calendar:view-mode", args=["list"]))

    response = client.get(reverse("calendar:calendar"))

    assertTemplateUsed(response, "calendar/calendar.html")
    assert "fullcalendar-container" in response.content.decode()


def test_unknown_view_mode_is_refused(client):
    assert client.post(reverse("calendar:view-mode", args=["week"])).status_code == 400


def test_add_get(client):
    response = client.get("/calendar/add")
    assert response.status_code == 200
    assertTemplateUsed(response, "calendar/form.html")
    assert response.context["edit"] is False


def test_add_post(client, user, event_data):
    response = client.post("/calendar/add", event_data)
    assert response.status_code == 204
    assert response["HX-Trigger"] == "eventsChanged"
    event = Event.objects.get(description=event_data["description"])
    assert event.user == user


def test_edit_get(client, event):
    response = client.get(f"/calendar/{event.id}/edit")
    assert response.status_code == 200
    assertTemplateUsed(response, "calendar/form.html")
    assert response.context["edit"] is True


def test_edit_post(client, event):
    data = {
        "date": "2022-12-29",
        "description": "File Answer, moved",
        "event_type": "Phone",
        "location": "555-1234",
    }
    response = client.post(f"/calendar/{event.id}/edit", data)
    assert response.status_code == 204
    event.refresh_from_db()
    assert str(event.date) == "2022-12-29"
    assert event.description == "File Answer, moved"
    assert event.event_type == "Phone"
    assert event.location == "555-1234"


def test_delete(client, event):
    response = client.post(f"/calendar/{event.id}/delete")
    assert response.status_code == 204
    assert not Event.objects.filter(pk=event.id).exists()


def test_delete_by_delete_method(client, event):
    response = client.delete(f"/calendar/{event.id}/delete")
    assert response.status_code == 204
    assert not Event.objects.filter(pk=event.id).exists()


def test_delete_needs_post(client, event):
    assert client.get(f"/calendar/{event.id}/delete").status_code == 405
    assert Event.objects.filter(pk=event.id).exists()


# -----------------------------------------------------
# edge case tests - nonexistent records and other users' records
# -----------------------------------------------------
def test_edit_nonexistent(client):
    assert client.get("/calendar/99999/edit").status_code == 404


def test_delete_nonexistent(client):
    assert client.post("/calendar/99999/delete").status_code == 404


def test_another_users_event_is_not_found(client, other_user):
    theirs = Event.objects.create(
        user=other_user, date="2030-01-01", description="Not yours"
    )

    assert client.get(f"/calendar/{theirs.id}/edit").status_code == 404
    assert client.post(f"/calendar/{theirs.id}/delete").status_code == 404
    assert Event.objects.filter(pk=theirs.id).exists()


def test_feed_and_list_show_only_the_users_events(client, user, other_user):
    mine = Event.objects.create(user=user, date="2030-03-04", description="Mine")
    Event.objects.create(user=other_user, date="2030-03-04", description="Theirs")

    feed = client.get(
        reverse("calendar:api"), {"start": "2030-03-01", "end": "2030-03-31"}
    ).json()
    assert [row["id"] for row in feed] == [str(mine.id)]

    client.post(reverse("calendar:view-mode", args=["list"]))
    rows = client.get(reverse("calendar:list")).context["objects"]
    assert list(rows) == [mine]


def test_feed_shapes_timed_and_all_day_events(client, user):
    timed = Event.objects.create(
        user=user,
        date="2030-03-04",
        start_time="09:00",
        end_time="10:30",
        description="Timed",
        event_type="Zoom",
        location="https://zoom.example/j/1",
    )
    all_day = Event.objects.create(user=user, date="2030-03-05", description="All day")

    feed = {
        row["id"]: row
        for row in client.get(
            reverse("calendar:api"), {"start": "2030-03-01", "end": "2030-03-31"}
        ).json()
    }

    assert feed[str(timed.id)]["start"] == "2030-03-04T09:00:00-05:00"
    assert feed[str(timed.id)]["end"] == "2030-03-04T10:30:00-05:00"
    assert feed[str(timed.id)]["allDay"] is False
    assert feed[str(timed.id)]["extendedProps"] == {
        "event_type": "Zoom",
        "location": "https://zoom.example/j/1",
    }
    assert feed[str(all_day.id)]["start"] == "2030-03-05"
    assert feed[str(all_day.id)]["allDay"] is True
