"""A user signed in to the Android app through the real OAuth flow
(authorize with PKCE, approve, trade the code for a token, all for the
API's address), and the app's side of the API."""

import base64
import hashlib
import importlib
import re
import uuid
from datetime import timedelta
from urllib.parse import parse_qs, urlencode, urlparse

import pytest
from django.apps import apps as django_apps
from django.conf import settings
from django.test import Client
from django.utils import timezone
from oauth2_provider.models import Application

from accounts.models import CustomUser
from apps.api.models import Tombstone
from apps.folders.models import Folder
from apps.tasks.models import Task

CLIENT_ID = "cloudportal-android"
REDIRECT_URI = "net.cloudportal.tasks:/oauth"


@pytest.fixture
def user():
    user = CustomUser.objects.create_user(
        "Ollie", "ollie@gmail.com", "clawboy", first_name="Ollie"
    )
    user.time_zone = "America/New_York"
    user.ntfy_topic = "ollie-topic"
    user.save()
    return user


@pytest.fixture
def other_user():
    user = CustomUser.objects.create_user(
        "Nico", "nico@gmail.com", "clawboy", first_name="Nico"
    )
    user.time_zone = "Europe/London"
    user.save()
    return user


@pytest.fixture
def browser(user):
    client = Client()
    client.login(username="Ollie", password="clawboy")
    return client


@pytest.fixture
def android_app():
    """Made by the migration (apps/api/migrations/0002_android_client.py);
    made again by it after a test that empties the database."""
    if not Application.objects.filter(client_id=CLIENT_ID).exists():
        migration = importlib.import_module("apps.api.migrations.0002_android_client")
        migration.add_client(django_apps, None)
    return Application.objects.get(client_id=CLIENT_ID)


def pkce_pair():
    verifier = "a" * 64
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def authorize_query(challenge, resource=None, client_id=CLIENT_ID):
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "scope": settings.CONNECTOR_SCOPE,
        "state": "xyz",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    if resource is not False:
        params["resource"] = resource or settings.API_URL
    return urlencode(params)


def approve(browser, challenge, resource=None):
    """Open the consent page and press Allow: the code the app gets back."""
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
    assert f"{back.scheme}:{back.path}" == REDIRECT_URI
    return parse_qs(back.query)["code"][0]


def trade(code, verifier, resource=None):
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "client_id": CLIENT_ID,
        "code_verifier": verifier,
    }
    if resource is not False:
        data["resource"] = resource or settings.API_URL
    response = Client().post("/oauth/token/", data)
    assert response.status_code == 200, response.content
    return response.json()


@pytest.fixture
def tokens(browser, android_app):
    verifier, challenge = pkce_pair()
    return trade(approve(browser, challenge), verifier)


def op(type, **fields):
    return {"id": str(uuid.uuid4()), "type": type, **fields}


class App:
    """The Android app's side of the API."""

    def __init__(self, token):
        self.client = Client()
        self.token = token

    def headers(self):
        return {"HTTP_AUTHORIZATION": f"Bearer {self.token}"} if self.token else {}

    def get(self, cursor=None):
        query = {"cursor": cursor} if cursor else {}
        return self.client.get("/api/v1/sync", query, **self.headers())

    def sync(self, cursor=None):
        response = self.get(cursor)
        assert response.status_code == 200, response.content
        return response.json()

    def post(self, body, **extra):
        return self.client.post(
            "/api/v1/ops",
            body,
            content_type="application/json",
            **self.headers(),
            **extra,
        )

    def send(self, *ops):
        response = self.post({"ops": list(ops)})
        assert response.status_code == 200, response.content
        return response.json()["results"]

    def ok(self, *ops):
        results = self.send(*ops)
        for result in results:
            assert result["ok"], result
        return results[-1] if len(results) == 1 else results


@pytest.fixture
def app(tokens):
    return App(tokens["access_token"])


@pytest.fixture
def other_app(other_user, android_app):
    client = Client()
    client.login(username="Nico", password="clawboy")
    verifier, challenge = pkce_pair()
    return App(trade(approve(client, challenge), verifier)["access_token"])


def settle(hours=1):
    """Make everything so far look an hour old, so a sync from now on sees
    only what changes next (a cursor's overlap reaches a little back)."""
    then = timezone.now() - timedelta(hours=hours)
    Task.objects.update(updated_at=then)
    Folder.objects.update(updated_at=then)
    Tombstone.objects.update(deleted_at=then)


def task_ids(data):
    return {task["id"] for task in data["tasks"]}


def by_id(data, task_id):
    return next(task for task in data["tasks"] if task["id"] == task_id)
