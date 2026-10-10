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


# -- notes encryption: the salt, the round count and the sealed key -------

SALT = "c2FsdHNhbHRzYWx0c2FsdA=="
WRAPPED = "aXZpdml2aXZpdml2Y2lwaGVydGV4dGNpcGhlcnRleHQ="


def _post_json(client, name, body):
    return client.post(reverse(name), data=body, content_type="application/json")


def _fresh(user):
    from accounts.models import CustomUser

    return CustomUser.objects.get(pk=user.pk)


def test_save_salt_records_salt_rounds_and_sealed_key(client, user):
    response = _post_json(
        client,
        "settings-encryption-save-salt",
        {"salt": SALT, "iterations": 600000, "wrapped_key": WRAPPED},
    )
    assert response.status_code == 200
    user = _fresh(user)
    assert (
        user.encryption_salt,
        user.encryption_iterations,
        user.encryption_wrapped_key,
    ) == (SALT, 600000, WRAPPED)


@pytest.mark.parametrize(
    "body",
    [
        {"salt": SALT, "wrapped_key": WRAPPED},
        {"salt": SALT, "wrapped_key": WRAPPED, "iterations": "lots"},
        {"salt": SALT, "wrapped_key": WRAPPED, "iterations": 99999},
        {"salt": SALT, "wrapped_key": WRAPPED, "iterations": 10_000_001},
        {"salt": SALT, "iterations": 600000},
        {"iterations": 600000, "wrapped_key": WRAPPED},
    ],
)
def test_save_salt_refuses_an_incomplete_body(client, user, body):
    response = _post_json(client, "settings-encryption-save-salt", body)
    assert response.status_code == 400
    assert _fresh(user).encryption_salt == ""


def test_a_key_made_before_the_count_was_recorded_counts_as_the_old_default(user):
    assert user.encryption_iterations == 100000
    assert user.encryption_wrapped_key == ""


def test_recovery_code_is_recorded_and_cleared(client, user):
    response = _post_json(
        client,
        "settings-encryption-recovery",
        {"recovery_salt": SALT, "recovery_wrapped_key": WRAPPED},
    )
    assert response.status_code == 200
    user = _fresh(user)
    assert (user.encryption_recovery_salt, user.encryption_recovery_wrapped_key) == (
        SALT,
        WRAPPED,
    )
    response = _post_json(client, "settings-encryption-recovery", {})
    assert response.json() == {"saved": True, "has_recovery": False}
    user = _fresh(user)
    assert (user.encryption_recovery_salt, user.encryption_recovery_wrapped_key) == (
        "",
        "",
    )


def test_recovery_code_needs_both_halves(client, user):
    response = _post_json(
        client, "settings-encryption-recovery", {"recovery_salt": SALT}
    )
    assert response.status_code == 400


def test_clearing_the_salt_forgets_every_encryption_setting(client, user):
    user.encryption_salt = SALT
    user.encryption_wrapped_key = WRAPPED
    user.encryption_recovery_salt = SALT
    user.encryption_recovery_wrapped_key = WRAPPED
    user.encryption_by_default = True
    user.save()
    assert _post_json(client, "settings-encryption-clear-salt", {}).status_code == 200
    user = _fresh(user)
    assert (
        user.encryption_salt,
        user.encryption_wrapped_key,
        user.encryption_recovery_salt,
        user.encryption_recovery_wrapped_key,
        user.encryption_by_default,
    ) == ("", "", "", "", True)


def test_new_notes_start_encrypted_while_encryption_is_on(client, user):
    from apps.notes.models import Note

    # the default stands from the start, but means nothing without a salt
    assert user.encryption_by_default is True
    client.post(reverse("notes:add"), {"title": "Before any key", "folder": ""})
    assert Note.objects.get(user=user, title="Before any key").is_encrypted is False

    user.encryption_salt = SALT
    user.encryption_wrapped_key = WRAPPED
    user.save()
    client.post(reverse("notes:add"), {"title": "Sealed from the start", "folder": ""})
    assert (
        Note.objects.get(user=user, title="Sealed from the start").is_encrypted is True
    )

    # the switch posts a form and comes back to the page
    response = client.post(reverse("settings-encryption-by-default", args=["off"]))
    assert response.status_code == 302
    assert response["Location"] == reverse("settings-encryption")
    assert _fresh(user).encryption_by_default is False
    client.post(reverse("notes:add"), {"title": "Plain", "folder": ""})
    assert Note.objects.get(user=user, title="Plain").is_encrypted is False

    # encrypt-all posts JSON and gets JSON
    response = client.post(
        reverse("settings-encryption-by-default", args=["on"]),
        data={},
        content_type="application/json",
    )
    assert response.json() == {"saved": True, "enabled": True}


def test_encryption_page_carries_its_config(client, user):
    user.encryption_salt = SALT
    user.encryption_iterations = 600000
    user.encryption_wrapped_key = WRAPPED
    user.save()
    html = client.get(reverse("settings-encryption")).content.decode()
    assert 'id="encryption-config"' in html
    assert '"iterations": 600000' in html
    assert WRAPPED in html
    assert "encryption-settings.js" in html


def test_the_notes_endpoint_carries_what_the_browser_search_needs(client, user):
    from apps.folders.models import Folder
    from apps.notes.models import Note

    folder = Folder.objects.create(user=user, name="Recipes", page="notes")
    note = Note.objects.create(
        user=user, title="Soup", content="carrots", folder=folder
    )
    data = client.get(reverse("settings-encryption-notes")).json()
    (row,) = [n for n in data["notes"] if n["id"] == note.id]
    assert row == {
        "id": note.id,
        "title": "Soup",
        "content": "carrots",
        "is_encrypted": False,
        "url": reverse("notes:note-view", args=[note.id]),
        "folder_name": "Recipes",
        "folder_url": reverse("folder-select", args=[folder.id, "notes"]),
    }
