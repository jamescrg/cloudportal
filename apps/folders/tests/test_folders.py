import pytest
from django.test.client import RequestFactory

from apps.contacts.models import Folder
from apps.folders.folders import get_task_folders

pytestmark = pytest.mark.django_db


def test_string(folder):
    folder = Folder.objects.get(name="Main")
    assert str(folder) == f"{folder.name}"


def test_content(user, folder):
    folder = Folder.objects.get(name="Main")
    expectedValues = {
        "user": user,
        "page": "favorites",
        "name": "Main",
        "home_column": 0,
        "home_rank": 0,
        "selected": 0,
        "active": 0,
    }
    for key, val in expectedValues.items():
        assert getattr(folder, key) == val


def test_home(client, folder):
    response = client.get(f"/folders/home/{folder.id}/notes")
    assert response.status_code == 302
    folder = Folder.objects.filter(pk=folder.id).get()
    assert folder.home_column == 1
    assert folder.home_rank == 1


def test_select_folder(client, folders):
    folder = Folder.objects.filter(name="Philosophy").get()
    response = client.get(f"/folders/{folder.id}/notes")
    assert response.status_code == 302


def test_select_task_folders(client, task_folders):
    folder1 = Folder.objects.filter(pk=task_folders[0].id).get()
    response = client.get(f"/folders/{folder1.id}/tasks")
    assert response.status_code == 302

    folder2 = Folder.objects.filter(pk=task_folders[1].id).get()
    response = client.get(f"/folders/{folder2.id}/tasks")
    assert response.status_code == 302

    response = client.get("/tasks/")
    assert folder2 == response.context["selected_folder"]


def test_insert(client):
    data = {
        "user": 1,
        "folder_id": 2,
        "page": "notes",
        "name": "Existentialism",
    }
    response = client.post("/folders/insert/notes", data)
    assert response.status_code == 302
    found = Folder.objects.filter(name="Existentialism").exists()
    assert found


def test_update(client, folder):
    data = {
        "name": "Atlanta",
    }
    response = client.post(f"/folders/update/{folder.id}/favorites", data)
    assert response.status_code == 302
    found = Folder.objects.filter(name="Atlanta").exists()
    assert found


def test_delete(client, folder):
    client.get(f"/folders/delete/{folder.id}/favorites")
    found = Folder.objects.filter(id=folder.id).exists()
    assert not found


def test_get_task_folders(user, task_folders):
    factory = RequestFactory()
    request = factory.get("/tasks")
    request.user = user
    folders = get_task_folders(request)
    assert len(folders) > 0
