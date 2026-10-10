import pytest
from django.urls import reverse
from pytest_django.asserts import assertTemplateUsed

pytestmark = pytest.mark.django_db


def test_url(client):
    response = client.get("/settings/")
    assert response.status_code == 200


def test_named_route(client):
    response = client.get(reverse("settings"))
    assert response.status_code == 200


def test_correct_template(client):
    response = client.get(reverse("settings"))
    assertTemplateUsed(response, "settings/content.html")


def test_home_icons_options(client, user):
    from accounts.models import CustomUser

    client.get("/settings/home-options/icons/disable")
    client.get("/settings/home-options/icons_muted/disable")
    user = CustomUser.objects.get(pk=user.pk)
    assert (user.home_icons, user.home_icons_muted) == (0, 0)
    client.get("/settings/home-options/icons/enable")
    client.get("/settings/home-options/icons_muted/enable")
    user = CustomUser.objects.get(pk=user.pk)
    assert (user.home_icons, user.home_icons_muted) == (1, 1)


def test_homepage_settings_show_the_icon_switches(client):
    html = client.get("/settings/homepage/").content.decode()
    assert "/settings/home-options/icons/disable" in html
    assert "/settings/home-options/icons_muted/disable" in html
