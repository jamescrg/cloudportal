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


def test_variants_are_offered(client):
    html = page_for(client, "matcha")
    assert "Matcha Lavender" in html
    assert "Hojicha Steam" in html


def test_with_no_theme_chosen_it_follows_the_device(client, user):
    user.theme = ""
    user.save()
    html = client.get(reverse("settings")).content.decode()
    assert "css/theme-auto.css" in html
