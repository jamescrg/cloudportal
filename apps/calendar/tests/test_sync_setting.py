"""Google Calendar sync is a setting of its own, apart from linking a
Google account. It starts off; turning it on adopts the events kept here;
the sync command only visits users who turned it on."""

from io import StringIO

import pytest
from django.core.management import call_command
from django.urls import reverse

import apps.calendar.sync as sync
from accounts.models import CustomUser
from apps.calendar.models import Event

pytestmark = pytest.mark.django_db


def test_sync_starts_off(user):
    assert user.calendar_sync is False


def test_the_settings_tab_shows_the_switch(client):
    response = client.get(reverse("settings-calendar"))

    assert response.status_code == 200
    assert response.context["subapp"] == "calendar"
    assert (
        reverse("settings-calendar") in client.get(reverse("settings")).content.decode()
    )


def test_turning_sync_on_and_off(client, user):
    response = client.get(
        reverse("settings-calendar-options", args=["google_sync", "on"])
    )
    assert response.status_code == 302
    user.refresh_from_db()
    assert user.calendar_sync is True

    client.get(reverse("settings-calendar-options", args=["google_sync", "off"]))
    user.refresh_from_db()
    assert user.calendar_sync is False


def test_an_unknown_value_changes_nothing(client, user):
    client.get(reverse("settings-calendar-options", args=["google_sync", "maybe"]))

    user.refresh_from_db()
    assert user.calendar_sync is False


def test_turning_sync_on_adopts_the_events_kept_here(client, user, monkeypatch):
    user.google_credentials = '{"token": "x"}'
    user.save()
    Event.objects.create(user=user, date="2030-03-04", description="Kept here")
    reconciled = []
    monkeypatch.setattr(sync, "reconcile", lambda u: reconciled.append(u))

    client.get(reverse("settings-calendar-options", args=["google_sync", "on"]))

    assert reconciled == [user]


def test_turning_sync_off_does_not_reconcile(client, user, monkeypatch):
    reconciled = []
    monkeypatch.setattr(sync, "reconcile", lambda u: reconciled.append(u))

    client.get(reverse("settings-calendar-options", args=["google_sync", "off"]))

    assert reconciled == []


def test_the_form_notes_a_missing_account_only_when_sync_is_on(client, user):
    note = "no Google account is connected"

    assert note not in client.get(reverse("calendar:add")).content.decode()

    user.calendar_sync = True
    user.save()
    assert note in client.get(reverse("calendar:add")).content.decode()

    user.google_credentials = '{"token": "x"}'
    user.save()
    assert note not in client.get(reverse("calendar:add")).content.decode()


def test_the_sync_command_visits_only_users_with_sync_on(user, other_user, monkeypatch):
    for u in (user, other_user):
        u.google_credentials = '{"token": "x"}'
    user.calendar_sync = True
    user.save()
    other_user.save()
    visited = []
    monkeypatch.setattr(
        sync, "scheduled_sync", lambda u: visited.append(u) or {"reconciled": {}}
    )

    call_command("sync_calendar", stdout=StringIO())

    assert visited == [user]
    assert CustomUser.objects.filter(calendar_sync=True).count() == 1


def test_one_user_s_failed_sync_leaves_the_rest_syncing(user, other_user, monkeypatch):
    for u in (user, other_user):
        u.google_credentials = '{"token": "x"}'
        u.calendar_sync = True
        u.save()
    visited = []

    def fake_sync(u):
        visited.append(u)
        if u == user:
            raise RuntimeError("Google is down")
        return {"reconciled": {}}

    monkeypatch.setattr(sync, "scheduled_sync", fake_sync)

    result = sync.sync_all()

    assert set(visited) == {user, other_user}
    assert result == {"synced": 1, "failed": 1}
