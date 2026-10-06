"""The Forward Invitations card in Settings: the address and the senders."""

import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db


def test_without_a_domain_the_card_says_so(client, settings):
    settings.CALENDAR_INBOUND_DOMAIN = ""

    html = client.get(reverse("settings-calendar")).content.decode()

    assert "not set up on this server" in html
    assert "Create address" not in html


def test_creating_renewing_and_removing_the_address(client, user, settings):
    settings.CALENDAR_INBOUND_DOMAIN = "in.example.com"
    assert "Create address" in client.get(reverse("settings-calendar")).content.decode()

    client.get(reverse("settings-calendar-options", args=["inbound_address", "new"]))
    user.refresh_from_db()
    first = user.calendar_inbound_token
    assert first
    html = client.get(reverse("settings-calendar")).content.decode()
    assert f"calendar-{first}@in.example.com" in html

    client.get(reverse("settings-calendar-options", args=["inbound_address", "new"]))
    user.refresh_from_db()
    assert user.calendar_inbound_token != first

    client.get(reverse("settings-calendar-options", args=["inbound_address", "clear"]))
    user.refresh_from_db()
    assert user.calendar_inbound_token is None


def test_saving_the_senders(client, user):
    response = client.post(
        reverse("settings-calendar-forward-from"),
        {"calendar_forward_from": " me@proton.me\nalso@example.com "},
    )

    assert response.status_code == 302
    user.refresh_from_db()
    assert user.calendar_forward_from == "me@proton.me\nalso@example.com"
