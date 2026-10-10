"""The home page's favorites folders become one ordered sequence.

Until now each folder on the home page had a column (1 to 5) and a rank
within it. The page now lays the folders out in as many columns as the
window allows, from one order: home_rank runs across all of a user's
folders, and home_column is 1 for a folder on the home page, 0 or null
otherwise. The old column-by-column reading order becomes the sequence,
so nothing moves.
"""

from django.db import migrations


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
        ("folders", "0009_folder_created_at_folder_updated_at"),
    ]

    operations = [
        migrations.RunPython(sequence, migrations.RunPython.noop),
    ]
