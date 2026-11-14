"""A user who has connected Claude: signed in through the real OAuth flow
(authorize with PKCE, approve, trade the code for a token), so every test
of a tool runs with a token as Claude would hold one."""

import base64
import hashlib
import re
from urllib.parse import parse_qs, urlencode, urlparse

import pytest
from django.conf import settings
from django.test import Client
from oauth2_provider.models import Application

from accounts.models import CustomUser

CALLBACK = "https://claude.ai/api/mcp/auth_callback"
CLIENT_ID = "https://claude.ai/oauth/test-client-metadata"


@pytest.fixture
def user():
    user = CustomUser.objects.create_user("Ollie", "ollie@gmail.com", "clawboy")
    user.time_zone = "America/New_York"
    user.save()
    return user


@pytest.fixture
def other_user():
    return CustomUser.objects.create_user("Nico", "nico@gmail.com", "clawboy")


@pytest.fixture
def browser(user):
    client = Client()
    client.login(username="Ollie", password="clawboy")
    return client


@pytest.fixture
def claude_app():
    """Claude as the toolkit stores it once its metadata document is read:
    a public client, sending the user back to claude.ai."""
    return Application.objects.create(
        name="Claude",
        client_id=CLIENT_ID,
        client_type=Application.CLIENT_PUBLIC,
        authorization_grant_type=Application.GRANT_AUTHORIZATION_CODE,
        redirect_uris=CALLBACK,
        skip_authorization=False,
    )


def pkce_pair():
    verifier = "v" * 64
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def authorize_query(challenge, resource=None):
    return urlencode(
        {
            "response_type": "code",
            "client_id": CLIENT_ID,
            "redirect_uri": CALLBACK,
            "scope": settings.CONNECTOR_SCOPE,
            "state": "xyz",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "resource": resource or settings.CONNECTOR_URL,
        }
    )


def approve(browser, challenge, resource=None):
    """Open the consent page and press Allow: the code Claude gets back."""
    page = browser.get("/oauth/authorize/?" + authorize_query(challenge, resource))
    assert page.status_code == 200, page.content
    html = page.content.decode()
    fields = dict(
        re.findall(r'<input type="hidden" name="(\w+)" value="([^"]*)"', html)
    )
    fields["allow"] = "Authorize"
    answer = browser.post(
        page.request["PATH_INFO"] + "?" + page.request["QUERY_STRING"], fields
    )
    assert answer.status_code == 302, answer.content
    back = urlparse(answer["Location"])
    assert f"{back.scheme}://{back.netloc}{back.path}" == CALLBACK
    return parse_qs(back.query)["code"][0]


def trade(code, verifier, resource=None):
    response = Client().post(
        "/oauth/token/",
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": CALLBACK,
            "client_id": CLIENT_ID,
            "code_verifier": verifier,
            "resource": resource or settings.CONNECTOR_URL,
        },
    )
    assert response.status_code == 200, response.content
    return response.json()


@pytest.fixture
def tokens(browser, claude_app):
    verifier, challenge = pkce_pair()
    return trade(approve(browser, challenge), verifier)


class Claude:
    """Claude's side of the connector: JSON-RPC over POST to /mcp."""

    def __init__(self, token):
        self.client = Client()
        self.token = token
        self.next_id = 0

    def post(self, message, **headers):
        if self.token:
            headers.setdefault("HTTP_AUTHORIZATION", f"Bearer {self.token}")
        return self.client.post(
            "/mcp", message, content_type="application/json", **headers
        )

    def rpc(self, method, params=None, **headers):
        self.next_id += 1
        message = {"jsonrpc": "2.0", "id": self.next_id, "method": method}
        if params is not None:
            message["params"] = params
        return self.post(message, **headers)

    def call(self, name, **arguments):
        response = self.rpc("tools/call", {"name": name, "arguments": arguments})
        assert response.status_code == 200, response.content
        return response.json()["result"]

    def ok(self, name, **arguments):
        result = self.call(name, **arguments)
        assert not result["isError"], result["content"][0]["text"]
        return result["structuredContent"]

    def fails(self, name, **arguments):
        result = self.call(name, **arguments)
        assert result["isError"]
        return result["content"][0]["text"]


@pytest.fixture
def claude(tokens):
    return Claude(tokens["access_token"])
