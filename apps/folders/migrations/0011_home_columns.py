"""The home page's favorites folders go back into columns, the user's own.

The sequence (0010) left it to the browser which column a folder landed
in. Now home_column is the folder's column, 1 to 5, and home_rank its
place in that column. Each user's sequence is dealt into five consecutive
runs of near-equal height, a folder's height being its name and its
shown favorites, which is close to what the balanced flow showed, so
little moves. Backwards, the columns read out into one sequence again.
"""

from django.db import migrations

COLUMNS = 5
# a folder's name and padding, in lines
HEADER = 3


def balance(heights, count):
    """Cut the sequence into up to count consecutive runs of near-equal
    total height, as a balanced multi-column layout does: a list of lists
    of indexes."""
    columns = [[]]
    target = sum(heights) / count
    filled = 0
    for i, height in enumerate(heights):
        if filled and len(columns) < count and filled + height / 2 > target:
            columns.append([])
            filled = 0
        columns[-1].append(i)
        filled += height
    return columns


def deal(apps, schema_editor):
    Folder = apps.get_model("folders", "Folder")
    Favorite = apps.get_model("favorites", "Favorite")
    on_home = Folder.objects.filter(page="favorites", home_column__gt=0)
    for user_id in on_home.values_list("user_id", flat=True).distinct():
        folders = list(on_home.filter(user_id=user_id).order_by("home_rank", "id"))
        heights = [
            HEADER + Favorite.objects.filter(folder=folder, home_rank__gt=0).count()
            for folder in folders
        ]
        for column, members in enumerate(balance(heights, COLUMNS), start=1):
            for rank, i in enumerate(members, start=1):
                Folder.objects.filter(pk=folders[i].pk).update(
                    home_column=column, home_rank=rank
                )


def sequence(apps, schema_editor):
    Folder = apps.get_model("folders", "Folder")
    on_home = Folder.objects.filter(page="favorites", home_column__gt=0)
    for user_id in on_home.values_list("user_id", flat=True).distinct():
        folders = on_home.filter(user_id=user_id).order_by(
            "home_column", "home_rank", "id"
        )
        for rank, folder in enumerate(list(folders), start=1):
            Folder.objects.filter(pk=folder.pk).update(home_column=1, home_rank=rank)


class Migration(migrations.Migration):

    dependencies = [
        ("folders", "0010_home_sequence"),
        ("favorites", "0010_site_icon"),
    ]

    operations = [
        migrations.RunPython(deal, sequence),
    ]
