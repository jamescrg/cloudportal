"""Settings every test starts from."""

import pytest


@pytest.fixture(autouse=True)
def notifications_as_in_production(settings):
    """Tests run on the dev machine's .env, which sets notifications apart
    from production's (config/settings.py: NOT_PRODUCTION). They start as
    production does, sending email and pushing to the topic as it stands;
    a test of the dev machine's behaviour sets these itself."""
    settings.NTFY_TOPIC_SUFFIX = ""
    settings.NOTIFY_TITLE_PREFIX = ""
    settings.EMAIL_NOTIFICATIONS = True
