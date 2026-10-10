import json
from pathlib import Path

import pytest
from django.core.cache import cache
from django.test import Client

from accounts.models import CustomUser


@pytest.fixture
def user():
    user = CustomUser.objects.create_user(
        username="Ollie",
        email="ollie@gmail.com",
        password="clawboy",
        search_engine="",
        zip=59840,
        home_events=1,
        home_events_hidden="1980-01-01",
        home_tasks=1,
        home_tasks_hidden="1980-01-01",
        home_search=0,
        favorites_folder=0,
        contacts_folder=0,
        contacts_contact=0,
        notes_folder=0,
        notes_note=0,
        tasks_folder=0,
        tasks_folders="",
        tasks_active_folder=0,
    )
    return user


@pytest.fixture
def client(user):
    client = Client()
    client.login(username="Ollie", password="clawboy")
    return client


FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def onecall():
    """A real One Call 3.0 response for Hampton Roads on 10 October 2026,
    alert descriptions trimmed (timezone_offset -14400)."""
    return json.loads((FIXTURES / "onecall.json").read_text())


@pytest.fixture(autouse=True)
def empty_cache():
    """LocMemCache keeps its contents across tests in one process."""
    cache.clear()
    yield
    cache.clear()
