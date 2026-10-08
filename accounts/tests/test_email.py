"""Sign-in is by email, so every account has one and no two share one."""

import pytest
from django.db import IntegrityError

from accounts.forms import CustomUserCreationForm
from accounts.models import CustomUser
from apps.settings.forms import ProfileForm

pytestmark = pytest.mark.django_db


def test_two_accounts_cannot_share_an_email_in_any_case():
    CustomUser.objects.create_user("ollie", "ollie@example.com", "pw")
    with pytest.raises(IntegrityError):
        CustomUser.objects.create_user("ollie2", "OLLIE@example.com", "pw")


def test_sign_up_needs_an_email():
    form = CustomUserCreationForm(
        data={
            "username": "new",
            "password1": "a-long-pass-phrase",
            "password2": "a-long-pass-phrase",
        }
    )
    assert "email" in form.errors


def test_the_profile_cannot_take_anothers_email():
    CustomUser.objects.create_user("ollie", "ollie@example.com", "pw")
    other = CustomUser.objects.create_user("max", "max@example.com", "pw")
    form = ProfileForm(
        data={"username": "max", "email": "Ollie@Example.com"}, instance=other
    )
    assert not form.is_valid()


def test_the_profile_cannot_empty_the_email():
    user = CustomUser.objects.create_user("ollie", "ollie@example.com", "pw")
    form = ProfileForm(data={"username": "ollie", "email": ""}, instance=user)
    assert "email" in form.errors
