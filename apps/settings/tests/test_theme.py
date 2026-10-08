"""Themes: an original theme loads its own colours alone; an atmospheric
variant loads its base theme's colours, the shared atmosphere and its own
file, and draws the weather behind the page."""

import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db


def page_for(client, theme):
    client.post(reverse("settings-theme"), {"theme": theme})
    return client.get(reverse("settings")).content.decode()


def test_original_theme_has_no_atmosphere(client):
    html = page_for(client, "hojicha")
    assert "css/theme-hojicha.css" in html
    assert "atmosphere.css" not in html
    assert 'class="atmos"' not in html


def test_matcha_lavender_builds_on_matcha(client):
    html = page_for(client, "matcha-lavender")
    assert "css/theme-matcha.css" in html
    assert "css/atmosphere.css" in html
    assert "css/theme-matcha-lavender.css" in html
    assert 'class="atmos"' in html


def test_matcha_mist_is_now_matcha_lavender(client):
    html = page_for(client, "matcha-mist")
    assert "css/theme-matcha-lavender.css" in html
    assert "css/theme-matcha-mist.css" not in html


def test_hojicha_steam_builds_on_hojicha(client):
    html = page_for(client, "hojicha-steam")
    hojicha = html.index("css/theme-hojicha.css")
    atmosphere = html.index("css/atmosphere.css")
    steam = html.index("css/theme-hojicha-steam.css")
    assert hojicha < atmosphere < steam
    assert 'class="atmos"' in html


def test_the_page_offers_the_base_themes_and_an_atmosphere_switch(client):
    html = page_for(client, "matcha")
    assert "Matcha" in html and "Hojicha" in html and "Auto" in html
    assert "Matcha Lavender" not in html
    assert 'role="switch"' in html and 'aria-checked="false"' in html


def test_the_atmosphere_switch_turns_the_variant_on_and_off(client):
    client.post(reverse("settings-theme"), {"theme": "matcha"})
    client.post(reverse("settings-theme-atmosphere"), {"atmosphere": "on"})
    assert client.session["theme"] == "matcha-lavender"
    html = client.get(reverse("settings")).content.decode()
    assert 'aria-checked="true"' in html
    client.post(reverse("settings-theme-atmosphere"), {"atmosphere": "off"})
    assert client.session["theme"] == "matcha"


def test_choosing_a_base_keeps_the_atmosphere(client):
    client.post(reverse("settings-theme"), {"theme": "hojicha-steam"})
    client.post(reverse("settings-theme"), {"theme": "matcha"})
    assert client.session["theme"] == "matcha-lavender"
    client.post(reverse("settings-theme"), {"theme": "auto"})
    assert client.session["theme"] == "auto"


def test_auto_has_no_atmosphere(client):
    client.post(reverse("settings-theme"), {"theme": "auto"})
    client.post(reverse("settings-theme-atmosphere"), {"atmosphere": "on"})
    assert client.session["theme"] == "auto"
    assert "disabled" in client.get(reverse("settings")).content.decode()


def test_with_no_theme_chosen_it_follows_the_device(client, user):
    html = client.get(reverse("settings")).content.decode()
    assert "css/theme-auto.css" in html


def test_the_theme_is_kept_for_the_device(client, user):
    client.post(reverse("settings-theme"), {"theme": "hojicha"})
    html = client.get(reverse("settings")).content.decode()
    assert "css/theme-hojicha.css" in html


def test_another_device_is_not_changed(client, user):
    from django.test import Client

    client.post(reverse("settings-theme"), {"theme": "hojicha"})
    other = Client()
    other.force_login(user)
    html = other.get(reverse("settings")).content.decode()
    assert "css/theme-auto.css" in html


def test_a_theme_that_isnt_one_is_ignored(client, user):
    client.post(reverse("settings-theme"), {"theme": "../../secrets"})
    assert "theme" not in client.session
    assert client.get(reverse("settings")).status_code == 200
