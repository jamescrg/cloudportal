"""Arranging the home page: the folders' order and a folder's favorites
are each set by one post after a drag, and a folder's chooser shows or
hides its favorites."""

import json

import pytest
from django.urls import reverse

from accounts.models import CustomUser
from apps.favorites.models import Favorite
from apps.folders.models import Folder

pytestmark = pytest.mark.django_db(transaction=True, reset_sequences=True)


def post_order(client, folders):
    return client.post(
        "/home/folders/order/", {"folders": json.dumps([f.id for f in folders])}
    )


def post_favorites(client, folder, favorites):
    return client.post(
        f"/home/folders/{folder.id}/favorites/",
        {"favorites": json.dumps([f.id for f in favorites])},
    )


def ranks(folders):
    return [Folder.objects.get(pk=f.id).home_rank for f in folders]


@pytest.fixture
def stranger():
    return CustomUser.objects.create_user("Stranger", "s@x.com", "pw")


# -- the folders' order -------------------------------------------------


def test_reorder_folders(client, folders):
    # Swiss, the last, dragged to the top; the rest keep their order
    response = post_order(client, [folders[17]] + folders[:17])
    assert response.status_code == 200 and response.json()["ok"]
    assert ranks(folders) == list(range(2, 19)) + [1]


def test_order_rejects_a_folder_that_is_not_the_users(client, folders, stranger):
    theirs = Folder.objects.create(
        user=stranger, page="favorites", name="Theirs", home_column=1, home_rank=1
    )
    assert post_order(client, [folders[0], theirs]).status_code == 403
    assert Folder.objects.get(pk=theirs.id).home_rank == 1


def test_order_rejects_bad_input(client, folders):
    assert client.post("/home/folders/order/", {"folders": "nope"}).status_code == 400
    assert client.get("/home/folders/order/").status_code == 405


# -- a folder's favorites ------------------------------------------------


def test_reorder_favorites(client, folders, favorites):
    order = [favorites[4], favorites[0], favorites[1], favorites[2], favorites[3]]
    response = post_favorites(client, folders[0], order)
    assert response.status_code == 200 and response.json()["ok"]
    assert [Favorite.objects.get(pk=f.id).home_rank for f in favorites] == [
        2,
        3,
        4,
        5,
        1,
    ]


def test_favorite_dropped_into_another_folder_moves_there(client, folders, favorites):
    # Favorite No. 3 dropped at the top of Dev's (empty) list
    post_favorites(client, folders[4], [favorites[2]])
    moved = Favorite.objects.get(pk=favorites[2].id)
    assert (moved.folder_id, moved.home_rank) == (folders[4].id, 1)
    # the others keep their order in the folder it left
    left = Favorite.objects.filter(folder_id=folders[0].id).order_by("home_rank")
    assert [f.name for f in left] == [
        "Favorite No. 1",
        "Favorite No. 2",
        "Favorite No. 4",
        "Favorite No. 5",
    ]


def test_favorites_rejects_a_folder_the_user_cannot_reach(client, favorites, stranger):
    theirs = Folder.objects.create(user=stranger, page="favorites", name="Theirs")
    assert post_favorites(client, theirs, [favorites[0]]).status_code == 404
    assert Favorite.objects.get(pk=favorites[0].id).folder_id != theirs.id


def test_favorites_rejects_someone_elses_favorite(client, folders, favorites, stranger):
    theirs = Favorite.objects.create(user=stranger, name="Theirs", home_rank=1)
    assert post_favorites(client, folders[0], [theirs]).status_code == 403
    assert Favorite.objects.get(pk=theirs.id).folder_id is None


# -- the chooser -----------------------------------------------------------


def test_chooser_lists_the_folders_favorites_with_the_shown_ticked(
    client, user, folders, favorites
):
    kept = Favorite.objects.create(user=user, folder=folders[0], name="Kept back")
    response = client.get(f"/home/folders/{folders[0].id}/choose/")
    assert response.status_code == 200
    html = response.content.decode()
    assert html.count('name="shown"') == 6
    assert html.count("checked") == 5
    assert "Kept back" in html
    assert reverse("home-favorite-shown", args=[kept.id]) in html


def test_chooser_refuses_a_folder_the_user_cannot_reach(client, stranger):
    theirs = Folder.objects.create(user=stranger, page="favorites", name="Theirs")
    assert client.get(f"/home/folders/{theirs.id}/choose/").status_code == 404


def test_showing_a_favorite_puts_it_at_the_end(client, user, folders, favorites):
    kept = Favorite.objects.create(user=user, folder=folders[0], name="Kept back")
    response = client.post(f"/home/favorites/{kept.id}/shown/", {"shown": "on"})
    assert response.status_code == 200
    assert Favorite.objects.get(pk=kept.id).home_rank == 6
    # the response is the folder's body, with the newcomer last
    html = response.content.decode()
    assert html.rindex("Kept back") > html.rindex("Favorite No. 5")
    assert "more in the folder" not in html


def test_hiding_a_favorite_keeps_it_in_the_folder(client, folders, favorites):
    response = client.post(f"/home/favorites/{favorites[1].id}/shown/")
    assert response.status_code == 200
    hidden = Favorite.objects.get(pk=favorites[1].id)
    assert (hidden.folder_id, hidden.home_rank) == (folders[0].id, 0)
    html = response.content.decode()
    assert "Favorite No. 2" not in html
    assert "1 more in the folder" in html


def test_shown_refuses_a_favorite_in_a_folder_the_user_cannot_reach(client, stranger):
    theirs = Folder.objects.create(user=stranger, page="favorites", name="Theirs")
    favorite = Favorite.objects.create(user=stranger, folder=theirs, name="x")
    assert (
        client.post(
            f"/home/favorites/{favorite.id}/shown/", {"shown": "on"}
        ).status_code
        == 404
    )


# -- the page ----------------------------------------------------------------


def test_home_page_lists_folders_in_order_with_their_favorites(
    client, user, folders, favorites
):
    Favorite.objects.create(user=user, folder=folders[0], name="Kept back")
    response = client.get("/home/")
    page = response.context["folders"]
    assert [f.name for f in page] == [f.name for f in folders]
    assert [f.name for f in page[0].favorites] == [
        f"Favorite No. {i}" for i in range(1, 6)
    ]
    assert page[0].hidden_count == 1
    assert page[1].favorites == [] and page[1].hidden_count == 0
    html = response.content.decode()
    assert "1 more in the folder" in html
