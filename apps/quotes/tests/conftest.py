import pytest
from django.test import Client

from accounts.models import CustomUser


@pytest.fixture
def user():
    return CustomUser.objects.create_user("Ollie", "ollie@gmail.com", "clawboy")


@pytest.fixture
def client(user):
    client = Client()
    client.login(username="Ollie", password="clawboy")
    return client
