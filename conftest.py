"""Settings every test starts from."""

import pytest


@pytest.fixture(autouse=True)
def notifications_as_in_production(settings):
    """Tests run on the dev machine's .env, which sets notifications apart
    from production's (config/settings.py: NOT_PRODUCTION). They start as
    production does, sending email and pushing to the topic as it stands;
    a test of the dev machine's behaviour sets these itself."""
    settings.NOT_PRODUCTION = False
    settings.NTFY_TOPIC_SUFFIX = ""
    settings.NOTIFY_TITLE_PREFIX = ""
    settings.EMAIL_NOTIFICATIONS = True
    settings.CALENDAR_INBOUND_PREFIX = "calendar-"
    # the older per-user addresses, until a test sets the calendar address
    settings.CALENDAR_INBOUND_ADDRESS = ""


@pytest.fixture(autouse=True)
def cache_in_memory(settings):
    """Tests never share the site's on-disk cache."""
    settings.CACHES = {
        "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}
    }


@pytest.fixture(autouse=True)
def fast_password_hasher(settings):
    """Django's real hasher is slow by design (about half a second per
    password on dev), and fixtures set a password for most test users."""
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
