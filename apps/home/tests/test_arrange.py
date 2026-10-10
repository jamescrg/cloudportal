"""Arranging the home page: a column's folders and a folder's favorites
are set, in order, by one post each after a drag."""

import json

import pytest

from apps.favorites.models import Favorite
from apps.folders.models import Folder

pytestmark = pytest.mark.django_db(transaction=True, reset_sequences=True)


def post_column(client, column, folders):
    return client.post(
        f"/home/columns/{column}/",
        {"folders": json.dumps([f.id for f in folders])},
    )


def post_favorites(client, folder, favorites):
    return client.post(
        f"/home/folders/{folder.id}/favorites/",
        {"favorites": json.dumps([f.id for f in favorites])},
    )


def ranks(folders):
    return [Folder.objects.get(pk=f.id).home_rank for f in folders]


def test_reorder_within_column(client, folders):
    # column 1 was Main, Entertainment, Local, Social
    response = post_column(client, 1, [folders[3], folders[0], folders[1], folders[2]])
    assert response.status_code == 200 and response.json()["ok"]
    assert ranks(folders[:4]) == [2, 3, 4, 1]
    assert all(
        f.home_column == 1
        for f in Folder.objects.filter(pk__in=[f.id for f in folders[:4]])
    )


def test_move_to_another_column(client, folders):
    # Dev (column 2) dropped between Main and Entertainment in column 1
    post_column(client, 1, [folders[0], folders[4], folders[1], folders[2], folders[3]])
    dev = Folder.objects.get(pk=folders[4].id)
    assert (dev.home_column, dev.home_rank) == (1, 2)
    assert ranks([folders[0], folders[1], folders[2], folders[3]]) == [1, 3, 4, 5]
    # the column it left keeps its order
    assert [
        f.name for f in Folder.objects.filter(home_column=2).order_by("home_rank")
    ] == [
        "Research",
        "Filing",
        "Food",
    ]


def test_column_rejects_a_folder_that_is_not_the_users(client, folders):
    from accounts.models import CustomUser

    stranger = CustomUser.objects.create_user("Stranger", "s@x.com", "pw")
    theirs = Folder.objects.create(
        user=stranger, page="favorites", name="Theirs", home_column=1, home_rank=1
    )
    response = post_column(client, 1, [folders[0], theirs])
    assert response.status_code == 403
    assert Folder.objects.get(pk=theirs.id).home_rank == 1


def test_column_rejects_bad_input(client, folders):
    assert client.post("/home/columns/1/", {"folders": "nope"}).status_code == 400
    assert post_column(client, 9, [folders[0]]).status_code == 400
    assert client.get("/home/columns/1/").status_code == 405


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


def test_favorites_rejects_a_folder_the_user_cannot_reach(client, favorites):
    from accounts.models import CustomUser

    stranger = CustomUser.objects.create_user("Stranger", "s@x.com", "pw")
    theirs = Folder.objects.create(user=stranger, page="favorites", name="Theirs")
    assert post_favorites(client, theirs, [favorites[0]]).status_code == 404
    assert Favorite.objects.get(pk=favorites[0].id).folder_id != theirs.id


def test_favorites_rejects_someone_elses_favorite(client, folders, favorites):
    from accounts.models import CustomUser

    stranger = CustomUser.objects.create_user("Stranger", "s@x.com", "pw")
    theirs = Favorite.objects.create(user=stranger, name="Theirs", home_rank=1)
    assert post_favorites(client, folders[0], [theirs]).status_code == 403
    assert Favorite.objects.get(pk=theirs.id).folder_id is None


def test_home_page_shows_folders_by_column_with_their_favorites(
    client, folders, favorites
):
    response = client.get("/home/")
    columns = response.context["columns"]
    assert [[f.name for f in column] for column in columns] == [
        ["Main", "Entertainment", "Local", "Social"],
        ["Dev", "Research", "Filing", "Food"],
        ["Philosophy", "Psych", "History", "Math"],
        ["Physics", "Anthro", "Chorus", "Annoying"],
        ["German", "Swiss"],
    ]
    assert [f.name for f in columns[0][0].favorites] == [
        f"Favorite No. {i}" for i in range(1, 6)
    ]
    assert columns[0][1].favorites == []
