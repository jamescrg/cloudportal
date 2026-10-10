import pytest
from django.test import Client

from accounts.models import CustomUser
from apps.favorites.models import Favorite
from apps.folders.models import Folder


@pytest.fixture
def user():
    user = CustomUser.objects.create_user(
        username="Ollie",
        email="ollie@gmail.com",
        password="clawboy",
        search_engine="",
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


@pytest.fixture
def folders(user):
    # one sequence of folders on the home page, in this order
    names = [
        "Main",
        "Entertainment",
        "Local",
        "Social",
        "Dev",
        "Research",
        "Filing",
        "Food",
        "Philosophy",
        "Psych",
        "History",
        "Math",
        "Physics",
        "Anthro",
        "Chorus",
        "Annoying",
        "German",
        "Swiss",
    ]

    folders = []
    for rank, name in enumerate(names, start=1):
        folders.append(
            Folder.objects.create(
                user=user,
                name=name,
                home_column=1,
                home_rank=rank,
                page="favorites",
            )
        )

    return folders


@pytest.fixture
def favorites(user, folders):
    favorites = []
    for i in range(1, 6):
        favorites.append(
            Favorite.objects.create(
                user=user,
                folder_id=1,
                name=f"Favorite No. {i}",
                description=f"Awesome {i}",
                home_rank=i,
            )
        )

    return favorites
