"""Settings every test starts from."""

from datetime import timedelta

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


@pytest.fixture
def connect_phone_app():
    """Connect a user's Android app, as signing in to it does: a call gives
    them an access token for its OAuth client (settings.ANDROID_CLIENT_ID),
    good for ``expires_in``, and returns it."""
    from django.conf import settings
    from django.utils import timezone
    from oauth2_provider.models import AccessToken, Application

    def connect(user, expires_in=timedelta(hours=1)):
        application, _ = Application.objects.get_or_create(
            client_id=settings.ANDROID_CLIENT_ID,
            defaults={
                "client_type": "public",
                "authorization_grant_type": "authorization-code",
            },
        )
        return AccessToken.objects.create(
            user=user,
            application=application,
            token=f"access-{user.pk}-{AccessToken.objects.count()}",
            expires=timezone.now() + expires_in,
            scope=settings.CONNECTOR_SCOPE,
        )

    return connect
