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


# -- notes encryption: the salt and the PBKDF2 round count ------------------


def _save_salt(client, body):
    return client.post(
        reverse("settings-encryption-save-salt"),
        data=body,
        content_type="application/json",
    )


def test_save_salt_records_the_round_count(client, user):
    from accounts.models import CustomUser

    response = _save_salt(
        client, {"salt": "c2FsdHNhbHRzYWx0c2FsdA==", "iterations": 600000}
    )
    assert response.status_code == 200
    user = CustomUser.objects.get(pk=user.pk)
    assert (user.encryption_salt, user.encryption_iterations) == (
        "c2FsdHNhbHRzYWx0c2FsdA==",
        600000,
    )


@pytest.mark.parametrize("iterations", [None, "lots", 99999, 10_000_001])
def test_save_salt_refuses_a_bad_round_count(client, user, iterations):
    from accounts.models import CustomUser

    body = {"salt": "c2FsdHNhbHRzYWx0c2FsdA=="}
    if iterations is not None:
        body["iterations"] = iterations
    response = _save_salt(client, body)
    assert response.status_code == 400
    user = CustomUser.objects.get(pk=user.pk)
    assert user.encryption_salt == ""


def test_a_key_made_before_the_count_was_recorded_counts_as_the_old_default(user):
    assert user.encryption_iterations == 100000


def test_encryption_page_shows_the_round_count(client, user):
    user.encryption_salt = "c2FsdHNhbHRzYWx0c2FsdA=="
    user.encryption_iterations = 600000
    user.save()
    html = client.get(reverse("settings-encryption")).content.decode()
    assert 'data-iterations="600000"' in html
    assert "const iterations = 600000;" in html
