"""Claude signs in through OAuth: discovery, the consent page, PKCE, the
token, and refreshing it; the endpoint answers only a valid token meant
for it."""

from datetime import timedelta

import pytest
from django.conf import settings
from django.test import Client
from django.utils import timezone
from oauth2_provider.models import AccessToken

from apps.connector.tests.conftest import (
    CLIENT_ID,
    Claude,
    approve,
    authorize_query,
    pkce_pair,
    trade,
)

pytestmark = pytest.mark.django_db


def test_the_endpoint_asks_for_sign_in_and_says_where():
    response = Client().post("/mcp", {}, content_type="application/json")

    assert response.status_code == 401
    challenge = response["WWW-Authenticate"]
    assert challenge.startswith("Bearer ")
    assert (
        f'resource_metadata="{settings.SITE_URL}/.well-known/'
        'oauth-protected-resource/mcp"'
    ) in challenge
    assert f'scope="{settings.CONNECTOR_SCOPE}"' in challenge


def test_a_bad_token_is_told_it_is_invalid():
    response = Claude("not-a-token").rpc("ping")

    assert response.status_code == 401
    assert 'error="invalid_token"' in response["WWW-Authenticate"]


def test_the_resource_metadata_names_the_connector_and_its_issuer():
    data = Client().get("/.well-known/oauth-protected-resource/mcp").json()

    assert data["resource"] == settings.CONNECTOR_URL
    assert data["authorization_servers"] == [settings.SITE_URL]
    assert data["scopes_supported"] == [settings.CONNECTOR_SCOPE]


def test_the_server_metadata_offers_what_claude_needs():
    data = Client().get("/.well-known/oauth-authorization-server").json()

    assert data["issuer"] == settings.SITE_URL
    assert data["client_id_metadata_document_supported"] is True
    assert "none" in data["token_endpoint_auth_methods_supported"]
    assert data["code_challenge_methods_supported"] == ["S256"]
    assert data["response_types_supported"] == ["code"]
    assert "password" not in data["grant_types_supported"]
    assert "registration_endpoint" not in data


def test_the_consent_page_needs_the_sites_sign_in(claude_app):
    _, challenge = pkce_pair()

    response = Client().get("/oauth/authorize/?" + authorize_query(challenge))

    assert response.status_code == 302
    assert "/accounts/login/" in response["Location"]


def test_the_consent_page_names_the_app_and_where_it_is_from(browser, claude_app):
    _, challenge = pkce_pair()

    page = browser.get("/oauth/authorize/?" + authorize_query(challenge)).content

    assert b"Connect Claude?" in page
    assert b"<strong>claude.ai</strong>" in page
    assert b"Read and change your tasks and calendar" in page


def test_the_flow_gives_a_token_for_the_connector(tokens):
    access = AccessToken.objects.get()

    assert tokens["token_type"] == "Bearer"
    assert tokens["refresh_token"]
    assert access.resource == [settings.CONNECTOR_URL]
    assert Claude(tokens["access_token"]).rpc("ping").status_code == 200


def test_a_wrong_code_verifier_gets_no_token(browser, claude_app):
    _, challenge = pkce_pair()
    code = approve(browser, challenge)

    response = Client().post(
        "/oauth/token/",
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": "https://claude.ai/api/mcp/auth_callback",
            "client_id": CLIENT_ID,
            "code_verifier": "w" * 64,
        },
    )

    assert response.status_code == 400


def test_a_token_for_another_resource_is_refused(browser, claude_app):
    verifier, challenge = pkce_pair()
    elsewhere = "https://example.com/mcp"
    tokens = trade(approve(browser, challenge, elsewhere), verifier, elsewhere)

    assert Claude(tokens["access_token"]).rpc("ping").status_code == 401


def test_an_expired_token_is_refused_and_a_refresh_brings_a_new_one(tokens):
    AccessToken.objects.update(expires=timezone.now() - timedelta(seconds=1))
    assert Claude(tokens["access_token"]).rpc("ping").status_code == 401

    response = Client().post(
        "/oauth/token/",
        {
            "grant_type": "refresh_token",
            "refresh_token": tokens["refresh_token"],
            "client_id": CLIENT_ID,
            "resource": settings.CONNECTOR_URL,
        },
    )

    assert response.status_code == 200, response.content
    fresh = response.json()
    assert fresh["refresh_token"] != tokens["refresh_token"]
    assert Claude(fresh["access_token"]).rpc("ping").status_code == 200


def test_disconnecting_in_settings_ends_the_access(browser, tokens, claude_app):
    page = browser.get("/settings/connected/").content
    assert b"Claude" in page
    assert settings.CONNECTOR_URL.encode() in page

    browser.post(f"/settings/connected/{claude_app.pk}/disconnect")

    assert Claude(tokens["access_token"]).rpc("ping").status_code == 401
    assert b"Nothing yet" in browser.get("/settings/connected/").content


def test_an_inactive_user_is_shut_out(user, tokens):
    user.is_active = False
    user.save()

    assert Claude(tokens["access_token"]).rpc("ping").status_code == 401
