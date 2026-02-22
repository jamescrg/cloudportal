import pytest
from django.urls import reverse
from pytest_django.asserts import assertTemplateUsed

from apps.tasks.models import Task

pytestmark = pytest.mark.django_db(transaction=True, reset_sequences=True)


# ------------------------------------
# urls and templates
# ------------------------------------


def test_content(client, user, tasks, folders):
    task = tasks[0]
    expectedValues = {
        "user": user,
        "folder": folders[0],
        "title": "Take out trash",
        "status": 0,
    }
    for key, val in expectedValues.items():
        assert getattr(task, key) == val


def test_string(client, tasks):
    task = tasks[0]
    assert str(task) == f"{task.title} : {task.id}"


# ------------------------------------
# task functionality
# ------------------------------------


def test_index(client):
    response = client.get("/tasks/")
    assert response.status_code == 200

    response = client.get(reverse("tasks"))
    assert response.status_code == 200

    response = client.get(reverse("tasks"))
    assertTemplateUsed(response, "tasks/content.html")


def test_status(client, task):
    response = client.get(f"/tasks/{task.id}/complete")
    assert response.status_code == 302
    task = Task.objects.filter(pk=task.id).get()
    assert task.status == 1


def test_add_data(user, client, folder):
    data = {
        "user": user,
        "folder_id": folder.id,
        "title": "Sweep garage",
    }
    response = client.post("/tasks/add", data)
    assert response.status_code == 302
    found = Task.objects.filter(folder=folder).exists()
    assert found


def test_edit(client, task):
    response = client.get(f"/tasks/{task.id}/edit")
    assert response.status_code == 200
    assert response.context["page"] == "tasks"
    assertTemplateUsed(response, "tasks/content.html")


def test_edit_data(user, client, folder, task):
    data = {
        "user": user,
        "folder_id": folder.id,
        "title": "Sweep garage",
        "priority": 5,
        "status": 0,
        "archived": False,
    }
    response = client.post(f"/tasks/{task.id}/edit", data)
    assert response.status_code == 302
    found = Task.objects.filter(title="Sweep garage").exists()
    assert found


def test_clear(client, tasks, folder):
    # Select the folder so clear operates on it
    client.get(f"/folders/{folder.id}/tasks")
    Task.objects.filter(folder=folder).update(status=1)
    client.get("/tasks/clear")
    assert not Task.objects.filter(folder=folder, archived=False).exists()
    assert Task.objects.filter(folder=folder, archived=True).exists()
