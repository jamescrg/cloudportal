"""Arranging the home page: the folders' columns and a folder's favorites
are each set by one post after a drag, and a folder's chooser shows or
hides its favorites."""

import importlib
import json

import pytest
from django.urls import reverse

from accounts.models import CustomUser
from apps.favorites.models import Favorite
from apps.folders.folders import toggle_home
from apps.folders.models import Folder

balance = importlib.import_module("apps.folders.migrations.0011_home_columns").balance

pytestmark = pytest.mark.django_db(transaction=True, reset_sequences=True)


def post_layout(client, columns):
    return client.post(
        "/home/layout/",
        {"columns": json.dumps([[f.id for f in column] for column in columns])},
    )


def post_favorites(client, folder, favorites):
    return client.post(
        f"/home/folders/{folder.id}/favorites/",
        {"favorites": json.dumps([f.id for f in favorites])},
    )


def place(folder):
    folder = Folder.objects.get(pk=folder.id)
    return (folder.home_column, folder.home_rank)


def board(client):
    """The home page's columns as lists of folder names."""
    response = client.get("/home/")
    return [[f.name for f in column] for column in response.context["columns"]]


@pytest.fixture
def stranger():
    return CustomUser.objects.create_user("Stranger", "s@x.com", "pw")


# -- the folders' columns ---------------------------------------------------


def test_the_page_shows_the_folders_by_column(client, folders):
    assert board(client) == [
        [f.name for f in folders[0:5]],
        [f.name for f in folders[5:10]],
        [f.name for f in folders[10:15]],
        [f.name for f in folders[15:18]],
    ]


def test_a_folder_moves_between_columns(client, folders):
    # Swiss, last in the fourth column, dragged to the top of the second;
    # the rest keep their places
    columns = [
        folders[0:5],
        [folders[17]] + folders[5:10],
        folders[10:15],
        folders[15:17],
    ]
    response = post_layout(client, columns)
    assert response.status_code == 200 and response.json()["ok"]
    assert place(folders[17]) == (2, 1)
    assert place(folders[5]) == (2, 2)
    assert place(folders[9]) == (2, 6)
    assert place(folders[16]) == (4, 2)
    assert place(folders[0]) == (1, 1)


def test_a_folder_starts_a_new_column(client, folders):
    columns = [
        folders[0:5],
        folders[5:10],
        folders[10:15],
        folders[15:17],
        [folders[17]],
    ]
    assert post_layout(client, columns).status_code == 200
    assert place(folders[17]) == (5, 1)
    assert board(client)[4] == ["Swiss"]


def test_a_column_left_empty_closes_up(client, folders):
    # the fourth column's three folders dragged into the third
    columns = [folders[0:5], folders[5:10], folders[10:18]]
    assert post_layout(client, columns).status_code == 200
    assert len(board(client)) == 3
    assert place(folders[17]) == (3, 8)


def test_layout_takes_no_more_than_five_columns(client, folders):
    columns = [[f] for f in folders[:6]]
    assert post_layout(client, columns).status_code == 400
    assert place(folders[5]) == (2, 1)


def test_layout_rejects_a_folder_that_is_not_the_users(client, folders, stranger):
    theirs = Folder.objects.create(
        user=stranger, page="favorites", name="Theirs", home_column=1, home_rank=1
    )
    assert post_layout(client, [[folders[0], theirs]]).status_code == 403
    assert place(theirs) == (1, 1)


def test_layout_rejects_bad_input(client, folders):
    assert client.post("/home/layout/", {"columns": "nope"}).status_code == 400
    assert client.post("/home/layout/", {"columns": "[1, 2]"}).status_code == 400
    assert client.post("/home/layout/", {"columns": '{"a": [1]}'}).status_code == 400
    assert client.get("/home/layout/").status_code == 405


def test_a_folder_put_on_home_joins_the_end_of_the_last_column(user, folders):
    folder = Folder.objects.create(user=user, page="favorites", name="Newcomer")
    toggle_home(folder)
    assert place(folder) == (4, 4)
    toggle_home(folder)
    assert place(folder) == (0, 0)


def test_the_sequence_is_dealt_into_columns_of_near_equal_height():
    # eighteen folders of a height fill four columns and leave the fifth short
    assert [len(c) for c in balance([3] * 18, 5)] == [4, 4, 4, 4, 2]
    # a tall folder takes a column to itself
    assert balance([3, 20, 3, 3, 3], 5) == [[0], [1], [2, 3], [4]]
    # fewer folders than columns each get their own
    assert balance([3, 3], 5) == [[0], [1]]
    assert balance([], 5) == [[]]


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


def test_hiding_a_favorite_keeps_it_in_the_folder(client, folders, favorites):
    response = client.post(f"/home/favorites/{favorites[1].id}/shown/")
    assert response.status_code == 200
    hidden = Favorite.objects.get(pk=favorites[1].id)
    assert (hidden.folder_id, hidden.home_rank) == (folders[0].id, 0)
    assert "Favorite No. 2" not in response.content.decode()


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


def test_home_page_lists_each_folder_with_its_shown_favorites(
    client, user, folders, favorites
):
    Favorite.objects.create(user=user, folder=folders[0], name="Kept back")
    response = client.get("/home/")
    first = response.context["columns"][0]
    assert [f.name for f in first] == [f.name for f in folders[:5]]
    assert [f.name for f in first[0].favorites] == [
        f"Favorite No. {i}" for i in range(1, 6)
    ]
    assert first[1].favorites == []
