"""The failed sign-in cooldown: free attempts, then doubling waits during
which no password is checked, cleared by a success or a quiet day, and the
same for names no account has."""

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from accounts import throttle
from accounts.models import CustomUser, LoginThrottle

pytestmark = pytest.mark.django_db

PASSWORD = "correct horse battery"


@pytest.fixture
def user():
    return CustomUser.objects.create_user("ollie", "ollie@example.com", PASSWORD)


def attempt(client, username, password):
    return client.post(reverse("login"), {"username": username, "password": password})


def fail(client, username, times):
    for _ in range(times):
        attempt(client, username, "wrong")


def test_right_password_signs_in(client, user):
    response = attempt(client, "ollie", PASSWORD)
    assert response.status_code == 302
    assert client.session["_auth_user_id"] == str(user.pk)


def test_free_attempts_have_no_wait(client, user):
    fail(client, "ollie", throttle.FREE_ATTEMPTS)
    assert not throttle.cooldown_remaining("ollie")
    assert attempt(client, "ollie", PASSWORD).status_code == 302


def test_past_the_free_attempts_a_wait_starts(client, user):
    fail(client, "ollie", throttle.FREE_ATTEMPTS)
    response = attempt(client, "ollie", "wrong")
    assert b"Too many attempts. Try again in 1 minute." in response.content
    assert throttle.cooldown_remaining("ollie") > timedelta(seconds=50)


def test_no_password_is_checked_during_the_wait(client, user):
    fail(client, "ollie", throttle.FREE_ATTEMPTS + 1)
    response = attempt(client, "ollie", PASSWORD)
    assert response.status_code == 200
    assert b"Too many attempts" in response.content
    assert "_auth_user_id" not in client.session


def test_the_waits_double_to_a_cap():
    waits = []
    for _ in range(throttle.FREE_ATTEMPTS + 6):
        waits.append(throttle.record_failure("ollie"))
        LoginThrottle.objects.update(locked_until=None)
    after_free = waits[throttle.FREE_ATTEMPTS :]  # noqa: E203
    minutes = [round(w.total_seconds() / 60) for w in after_free]
    assert minutes == [1, 2, 4, 8, 15, 15]


def test_a_success_clears_the_slate(client, user):
    fail(client, "ollie", throttle.FREE_ATTEMPTS)
    attempt(client, "ollie", PASSWORD)
    assert not LoginThrottle.objects.exists()


def test_a_quiet_day_forgets(client, user):
    fail(client, "ollie", throttle.FREE_ATTEMPTS)
    LoginThrottle.objects.update(last_failure=timezone.now() - timedelta(days=2))
    attempt(client, "ollie", "wrong")
    assert LoginThrottle.objects.get().failures == 1


def test_the_wait_passes(client, user):
    fail(client, "ollie", throttle.FREE_ATTEMPTS + 1)
    LoginThrottle.objects.update(locked_until=timezone.now() - timedelta(seconds=1))
    assert attempt(client, "ollie", PASSWORD).status_code == 302


def test_case_does_not_dodge_the_count(client, user):
    fail(client, "Ollie", throttle.FREE_ATTEMPTS)
    response = attempt(client, "OLLIE", "wrong")
    assert b"Too many attempts" in response.content


def test_unknown_names_wait_just_the_same(client):
    fail(client, "nobody", throttle.FREE_ATTEMPTS)
    response = attempt(client, "nobody", "wrong")
    assert b"Too many attempts. Try again in 1 minute." in response.content


def test_next_stays_on_the_site(client, user):
    url = reverse("login") + "?next=https://evil.example/"
    response = client.post(url, {"username": "ollie", "password": PASSWORD})
    assert response.url == reverse("home")


def test_next_on_the_site_is_followed(client, user):
    url = reverse("login") + "?next=/tasks/"
    response = client.post(url, {"username": "ollie", "password": PASSWORD})
    assert response.url == "/tasks/"


def test_admin_signs_in_through_the_site(client):
    response = client.get("/admin/login/?next=/admin/")
    assert response.status_code == 302
    assert response.url.startswith(reverse("login"))
