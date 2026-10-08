"""Two-step sign-in with an authenticator app: the codes, the second step
of signing in, recovery codes, and setting it up and turning it off in
Settings, with the ways around it shut."""

import time

import pyotp
import pytest
from django.urls import reverse

from accounts import throttle, totp
from accounts.models import CustomUser, RecoveryCode
from apps.settings.security import SETUP_KEY

pytestmark = pytest.mark.django_db

PASSWORD = "correct horse battery"
SECRET = pyotp.random_base32()


def code(offset=0, secret=SECRET):
    otp = pyotp.TOTP(secret)
    return otp.generate_otp(int(time.time()) // otp.interval + offset)


@pytest.fixture
def user():
    return CustomUser.objects.create_user("ollie", "ollie@example.com", PASSWORD)


@pytest.fixture
def protected(user):
    totp.enable(user, SECRET, None)
    return user


def sign_in(client, next_url=""):
    url = reverse("login") + (f"?next={next_url}" if next_url else "")
    return client.post(url, {"email": "ollie@example.com", "password": PASSWORD})


def give_code(client, value):
    return client.post(reverse("login-verify"), {"code": value})


def signed_in(client):
    return "_auth_user_id" in client.session


# The codes


def test_a_code_from_now_or_a_step_either_side_matches():
    for offset in (-1, 0, 1):
        assert totp.matching_step(SECRET, code(offset)) is not None


def test_a_code_two_steps_off_does_not():
    assert totp.matching_step(SECRET, code(-2)) is None
    assert totp.matching_step(SECRET, code(2)) is None


def test_spaces_in_a_code_are_forgiven():
    value = code()
    assert totp.matching_step(SECRET, f"{value[:3]} {value[3:]}") is not None


def test_a_code_is_taken_once(protected):
    value = code()
    assert totp.verify(protected, value)
    assert not totp.verify(protected, value)


def test_an_older_code_after_a_newer_one_is_refused(protected):
    assert totp.verify(protected, code(0))
    assert not totp.verify(protected, code(-1))


def test_the_app_entry_is_marked_off_production(settings, user):
    settings.SITE_NAME = "cloudportal.link"
    settings.NOT_PRODUCTION = True
    assert "issuer=cloudportal.link%20%28dev%29" in totp.provisioning_uri(user, SECRET)
    settings.NOT_PRODUCTION = False
    assert "issuer=cloudportal.link&" in totp.provisioning_uri(user, SECRET) + "&"


# Signing in


def test_without_the_app_the_password_signs_in(client, user):
    assert sign_in(client).status_code == 302
    assert signed_in(client)


def test_with_the_app_the_password_alone_does_not(client, protected):
    response = sign_in(client)
    assert response.url == reverse("login-verify")
    assert not signed_in(client)


def test_the_right_code_signs_in(client, protected):
    sign_in(client)
    response = give_code(client, code())
    assert response.status_code == 302
    assert signed_in(client)


def test_next_survives_the_second_step(client, protected):
    sign_in(client, next_url="/tasks/")
    assert give_code(client, code()).url == "/tasks/"


def test_a_wrong_code_does_not_sign_in(client, protected):
    sign_in(client)
    response = give_code(client, "000000" if code() != "000000" else "111111")
    assert b"That code didn&#x27;t work." in response.content
    assert not signed_in(client)


def test_a_code_used_to_sign_in_cannot_sign_in_again(client, protected):
    value = code()
    sign_in(client)
    give_code(client, value)
    client.logout()
    sign_in(client)
    give_code(client, value)
    assert not signed_in(client)


def test_wrong_codes_count_toward_the_cooldown(client, protected):
    sign_in(client)
    for _ in range(throttle.FREE_ATTEMPTS):
        give_code(client, "abcdef")
    response = give_code(client, "abcdef")
    assert b"Too many attempts" in response.content
    # The password has to be given again, after the wait
    assert give_code(client, code()).url == reverse("login")
    assert b"Too many attempts" in sign_in(client).content


def test_the_password_step_does_not_clear_the_count(client, protected):
    for _ in range(throttle.FREE_ATTEMPTS):
        sign_in(client)
        give_code(client, "abcdef")
    sign_in(client)
    assert b"Too many attempts" in give_code(client, "abcdef").content


def test_the_second_step_needs_the_first(client, protected):
    assert client.get(reverse("login-verify")).url == reverse("login")
    assert give_code(client, code()).url == reverse("login")
    assert not signed_in(client)


def test_the_second_step_runs_out(client, protected):
    sign_in(client)
    session = client.session
    session["pending_since"] = time.time() - 600
    session.save()
    assert give_code(client, code()).url == reverse("login")
    assert not signed_in(client)


def test_a_recovery_code_signs_in_once(client, protected):
    codes = totp.make_recovery_codes(protected)
    sign_in(client)
    give_code(client, codes[0].upper())
    assert signed_in(client)
    client.logout()
    sign_in(client)
    give_code(client, codes[0])
    assert not signed_in(client)
    assert totp.recovery_codes_left(protected) == totp.RECOVERY_CODE_COUNT - 1


def test_recovery_codes_are_kept_only_as_hashes(protected):
    codes = totp.make_recovery_codes(protected)
    stored = set(RecoveryCode.objects.values_list("code_hash", flat=True))
    assert not stored & set(codes)


# Settings


def setup(client, user):
    client.force_login(user)
    client.post(reverse("settings-security-start"))
    return client.session[SETUP_KEY]


def test_set_up_shows_a_qr_code_and_waits_for_a_code(client, user):
    setup(client, user)
    response = client.get(reverse("settings-security"))
    assert b"<svg" in response.content
    user.refresh_from_db()
    assert not user.totp_secret


def test_the_right_code_turns_it_on_and_shows_recovery_codes(client, user):
    secret = setup(client, user)
    response = client.post(
        reverse("settings-security-confirm"), {"code": code(secret=secret)}
    )
    user.refresh_from_db()
    assert user.totp_secret == secret
    assert len(response.context["new_codes"]) == totp.RECOVERY_CODE_COUNT


def test_the_confirming_code_cannot_then_sign_in(client, user):
    secret = setup(client, user)
    value = code(secret=secret)
    client.post(reverse("settings-security-confirm"), {"code": value})
    user.refresh_from_db()
    assert not totp.verify(user, value)


def test_a_wrong_code_leaves_it_off(client, user):
    setup(client, user)
    response = client.post(reverse("settings-security-confirm"), {"code": "abc"})
    assert response.context["setup_error"]
    user.refresh_from_db()
    assert not user.totp_secret


def test_turning_off_needs_the_password_and_a_code(client, protected):
    client.force_login(protected)
    url = reverse("settings-security-disable")
    client.post(url, {"password": "wrong", "code": code()})
    client.post(url, {"password": PASSWORD, "code": "abcdef"})
    protected.refresh_from_db()
    assert protected.totp_secret
    client.post(url, {"password": PASSWORD, "code": code()})
    protected.refresh_from_db()
    assert not protected.totp_secret
    assert not RecoveryCode.objects.exists()


def test_guessing_the_password_to_turn_it_off_waits(client, protected):
    client.force_login(protected)
    url = reverse("settings-security-disable")
    for _ in range(throttle.FREE_ATTEMPTS + 1):
        client.post(url, {"password": "wrong", "code": code()})
    response = client.post(url, {"password": PASSWORD, "code": code()})
    assert "Too many attempts" in response.context["disable_error"]
    protected.refresh_from_db()
    assert protected.totp_secret


def test_new_recovery_codes_replace_the_old(client, protected):
    old = totp.make_recovery_codes(protected)
    client.force_login(protected)
    response = client.post(reverse("settings-security-recovery"), {"code": code()})
    assert set(response.context["new_codes"]).isdisjoint(old)
    assert not totp.use_recovery_code(protected, old[0])
