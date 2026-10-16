"""The Forward Invitations card in Settings: the calendar address, the
user's older one, and the senders."""

import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db


def test_without_an_address_the_card_says_so(client, settings):
    settings.CALENDAR_INBOUND_ADDRESS = ""

    html = client.get(reverse("settings-calendar")).content.decode()

    assert "not set up on this server" in html


def test_the_older_address_can_be_retired(client, user, settings):
    settings.CALENDAR_INBOUND_DOMAIN = "in.example.com"
    settings.CALENDAR_INBOUND_ADDRESS = "calendar@in.example.com"
    user.calendar_inbound_token = "abc"
    user.save()
    html = client.get(reverse("settings-calendar")).content.decode()
    assert "calendar@in.example.com" in html
    assert "calendar-abc@in.example.com" in html

    client.get(reverse("settings-calendar-options", args=["inbound_address", "clear"]))
    user.refresh_from_db()
    assert user.calendar_inbound_token is None
    html = client.get(reverse("settings-calendar")).content.decode()
    assert "calendar-abc@in.example.com" not in html


def test_saving_the_senders(client, user):
    response = client.post(
        reverse("settings-calendar-forward-from"),
        {"calendar_forward_from": " me@proton.me\nalso@example.com "},
    )

    assert response.status_code == 302
    user.refresh_from_db()
    assert user.calendar_forward_from == "me@proton.me\nalso@example.com"
