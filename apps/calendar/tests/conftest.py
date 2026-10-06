import pytest
from django.test import Client

from accounts.models import CustomUser
from apps.calendar.models import Event


@pytest.fixture
def user():
    return CustomUser.objects.create_user("Ollie", "ollie@gmail.com", "clawboy")


@pytest.fixture
def other_user():
    return CustomUser.objects.create_user("Nico", "nico@gmail.com", "clawboy")


@pytest.fixture
def client(user):
    client = Client()
    client.login(username="Ollie", password="clawboy")
    return client


@pytest.fixture
def event(user):
    return Event.objects.create(user=user, date="2022-12-28", description="File Answer")


@pytest.fixture
def event_data():
    return {"date": "2022-12-28", "description": "File Answer"}
