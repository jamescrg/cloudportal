"""The account menu (who is signed in, Settings, Log out) and Sign Out
Everywhere on the Security page."""

import re

import pytest
from django.contrib.auth.base_user import AbstractBaseUser
from django.test import Client
from django.urls import reverse

from accounts.models import CustomUser

pytestmark = pytest.mark.django_db


@pytest.fixture
def user():
    return CustomUser.objects.create_user(
        "james", "james@example.com", "pw", first_name="James", last_name="Craig"
    )


def signed_in_client(user):
    client = Client()
    client.force_login(user)
    return client


def test_the_menu_shows_who_is_signed_in_and_logs_out(user):
    html = signed_in_client(user).get(reverse("home")).content.decode()
    assert "James Craig" in html
    assert "james@example.com" in html
    assert f'action="{reverse("logout")}"' in html
    assert re.search(r'account-initials">\s*JC\s*<', html)


def test_log_out_signs_out(user):
    client = signed_in_client(user)
    client.post(reverse("logout"))
    assert "_auth_user_id" not in client.session


def test_the_session_page_is_gone(user):
    response = signed_in_client(user).get("/settings/session/")
    assert response.status_code == 404


def test_before_any_sign_out_the_hash_is_djangos(user):
    # Adding the count signed no one out
    assert user.get_session_auth_hash() == AbstractBaseUser.get_session_auth_hash(user)


def test_sign_out_everywhere_ends_the_others_and_keeps_this_one(user):
    here = signed_in_client(user)
    phone = signed_in_client(user)
    response = here.post(reverse("settings-security-sign-out"))
    assert response.context["signed_out_elsewhere"]

    assert here.get(reverse("home")).status_code == 200
    assert phone.get(reverse("home")).status_code == 302


def test_sign_out_everywhere_twice_still_keeps_this_one(user):
    here = signed_in_client(user)
    here.post(reverse("settings-security-sign-out"))
    here.post(reverse("settings-security-sign-out"))
    assert here.get(reverse("home")).status_code == 200
