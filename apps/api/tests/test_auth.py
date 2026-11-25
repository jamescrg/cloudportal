"""The Android app signs in through the site's OAuth provider as a client
of its own, and the API answers only a valid token meant for it; the
connector's tokens and the app's are each refused by the other."""

from datetime import timedelta

import pytest
from django.conf import settings
from django.test import Client
from django.utils import timezone
from oauth2_provider.models import AccessToken, Application

from apps.api.tests.conftest import (
    CLIENT_ID,
    App,
    approve,
    authorize_query,
    pkce_pair,
    trade,
)
from apps.connector.tests.conftest import (
    CALLBACK,
    CLIENT_ID as CLAUDE_CLIENT_ID,
    Claude,
    approve as claude_approve,
    pkce_pair as claude_pkce_pair,
    trade as claude_trade,
)

pytestmark = pytest.mark.django_db


def test_the_migration_registers_the_app_as_a_public_client(android_app):
    assert android_app.name == "CloudPortal for Android"
    assert android_app.client_type == Application.CLIENT_PUBLIC
    assert android_app.authorization_grant_type == Application.GRANT_AUTHORIZATION_CODE
    assert android_app.redirect_uris == "net.cloudportal.tasks:/oauth"
    assert android_app.client_secret == ""


def test_no_token_is_asked_to_sign_in():
    for response in (
        Client().get("/api/v1/sync"),
        Client().post("/api/v1/ops", {"ops": []}, content_type="application/json"),
    ):
        assert response.status_code == 401
        assert response.json()["error"]
        assert response["WWW-Authenticate"].startswith("Bearer ")


def test_a_bad_token_is_told_it_is_invalid():
    response = App("not-a-token").get()

    assert response.status_code == 401
    assert 'error="invalid_token"' in response["WWW-Authenticate"]


def test_the_consent_page_names_the_app_as_the_sites_own(browser, android_app):
    _, challenge = pkce_pair()

    page = browser.get("/oauth/authorize/?" + authorize_query(challenge)).content

    assert b"Connect CloudPortal for Android?" in page
    assert b"CloudPortal's own app" in page
    assert b"an unknown site" not in page
    assert b"can't delete anything" not in page


def test_the_flow_gives_a_token_for_the_api(tokens):
    access = AccessToken.objects.get()

    assert tokens["token_type"] == "Bearer"
    assert tokens["refresh_token"]
    assert tokens["expires_in"] == 3600
    assert access.resource == [settings.API_URL]
    assert App(tokens["access_token"]).get().status_code == 200


def test_another_scheme_is_not_allowed_back_to(browser, android_app):
    _, challenge = pkce_pair()
    query = authorize_query(challenge).replace(
        "net.cloudportal.tasks", "net.elsewhere.tasks"
    )

    response = browser.get("/oauth/authorize/?" + query)

    assert response.status_code == 400


def test_a_token_without_a_resource_is_taken(browser, android_app):
    verifier, challenge = pkce_pair()
    tokens = trade(approve(browser, challenge, False), verifier, False)

    assert AccessToken.objects.get().resource == []
    assert App(tokens["access_token"]).get().status_code == 200


def test_the_apps_token_is_refused_by_the_connector(tokens, browser, android_app):
    assert Claude(tokens["access_token"]).rpc("ping").status_code == 401

    # Even one not restricted to the API
    verifier, challenge = pkce_pair()
    open_tokens = trade(approve(browser, challenge, False), verifier, False)
    assert Claude(open_tokens["access_token"]).rpc("ping").status_code == 401


def test_a_connector_token_is_refused_by_the_api(browser):
    Application.objects.create(
        name="Claude",
        client_id=CLAUDE_CLIENT_ID,
        client_type=Application.CLIENT_PUBLIC,
        authorization_grant_type=Application.GRANT_AUTHORIZATION_CODE,
        redirect_uris=CALLBACK,
    )
    verifier, challenge = claude_pkce_pair()
    tokens = claude_trade(claude_approve(browser, challenge), verifier)

    assert Claude(tokens["access_token"]).rpc("ping").status_code == 200
    assert App(tokens["access_token"]).get().status_code == 401


def test_a_token_for_another_resource_is_refused(browser, android_app):
    verifier, challenge = pkce_pair()
    elsewhere = "https://example.com/api/v1/"
    tokens = trade(approve(browser, challenge, elsewhere), verifier, elsewhere)

    assert App(tokens["access_token"]).get().status_code == 401


def test_an_expired_token_is_refused_and_a_refresh_rotates(tokens):
    AccessToken.objects.update(expires=timezone.now() - timedelta(seconds=1))
    assert App(tokens["access_token"]).get().status_code == 401

    response = Client().post(
        "/oauth/token/",
        {
            "grant_type": "refresh_token",
            "refresh_token": tokens["refresh_token"],
            "client_id": CLIENT_ID,
        },
    )

    assert response.status_code == 200, response.content
    fresh = response.json()
    assert fresh["refresh_token"] != tokens["refresh_token"]
    assert App(fresh["access_token"]).get().status_code == 200
    # The fresh token keeps the audience
    access = AccessToken.objects.get(
        token_checksum__isnull=False, expires__gt=timezone.now()
    )
    assert access.resource == [settings.API_URL]


def test_an_inactive_user_is_shut_out(user, tokens):
    user.is_active = False
    user.save()

    assert App(tokens["access_token"]).get().status_code == 401


def test_revoking_the_token_ends_the_access(tokens):
    response = Client().post(
        "/oauth/revoke_token/",
        {"token": tokens["access_token"], "client_id": CLIENT_ID},
    )

    assert response.status_code == 200
    assert App(tokens["access_token"]).get().status_code == 401


def test_the_app_is_listed_in_settings_and_can_be_disconnected(
    browser, tokens, android_app
):
    page = browser.get("/settings/connected/").content
    assert b"CloudPortal for Android" in page

    browser.post(f"/settings/connected/{android_app.pk}/disconnect")

    assert App(tokens["access_token"]).get().status_code == 401
    assert b"CloudPortal for Android" not in browser.get("/settings/connected/").content
