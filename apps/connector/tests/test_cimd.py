"""claude.ai's client metadata document lists a JWT bearer grant beside
the authorization code; it is still read, for the grants offered here."""

import pytest
from oauth2_provider.cimd import resolve_cimd_application
from oauth2_provider.models import Application

from apps.connector import cimd

pytestmark = pytest.mark.django_db

CLAUDE_AI = "https://claude.ai/oauth/mcp-oauth-client-metadata"

# As claude.ai published it on 2026-11-14
DOCUMENT = {
    "client_id": CLAUDE_AI,
    "client_name": "Claude",
    "client_uri": "https://claude.ai",
    "redirect_uris": ["https://claude.ai/api/mcp/auth_callback"],
    "grant_types": [
        "authorization_code",
        "refresh_token",
        "urn:ietf:params:oauth:grant-type:jwt-bearer",
    ],
    "response_types": ["code"],
    "token_endpoint_auth_method": "none",
}


@pytest.fixture
def published(monkeypatch):
    """claude.ai's document, served without going to the network."""

    def fetch(self, client_id):
        return dict(DOCUMENT), 300

    monkeypatch.setattr(cimd.SafeMetadataFetcher, "fetch", fetch)


def test_only_the_offered_grants_are_kept(published):
    metadata, _ = cimd.OfferedGrantsFetcher().fetch(CLAUDE_AI)

    assert metadata["grant_types"] == ["authorization_code", "refresh_token"]


def test_claude_ai_is_registered_from_its_document(published):
    resolve_cimd_application(CLAUDE_AI, request=None)

    app = Application.objects.get(client_id=CLAUDE_AI)
    assert app.name == "Claude"
    assert app.client_type == Application.CLIENT_PUBLIC
    assert app.authorization_grant_type == Application.GRANT_AUTHORIZATION_CODE
    assert app.redirect_uris == "https://claude.ai/api/mcp/auth_callback"


def test_a_document_offering_nothing_here_is_still_refused(monkeypatch):
    def fetch(self, client_id):
        return {**DOCUMENT, "grant_types": ["client_credentials"]}, 300

    monkeypatch.setattr(cimd.SafeMetadataFetcher, "fetch", fetch)

    assert resolve_cimd_application(CLAUDE_AI, request=None) is None
    assert not Application.objects.filter(client_id=CLAUDE_AI).exists()
