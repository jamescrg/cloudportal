"""The CloudPortal Android app, as an OAuth client of the site: public (it
keeps no secret; PKCE stands for one), signing in by authorization code and
returning to the app by its own URI scheme. Made here so it is there on
every deploy."""

from django.db import migrations

CLIENT_ID = "cloudportal-android"


def add_client(apps, schema_editor):
    Application = apps.get_model("oauth2_provider", "Application")
    Application.objects.get_or_create(
        client_id=CLIENT_ID,
        defaults={
            "name": "CloudPortal for Android",
            "client_type": "public",
            "authorization_grant_type": "authorization-code",
            "redirect_uris": "net.cloudportal.tasks:/oauth",
            "client_secret": "",
            "hash_client_secret": False,
            "skip_authorization": False,
            "algorithm": "",
        },
    )


def remove_client(apps, schema_editor):
    Application = apps.get_model("oauth2_provider", "Application")
    Application.objects.filter(client_id=CLIENT_ID).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("api", "0001_initial"),
        ("oauth2_provider", "0022_refreshtoken_token_family_index"),
    ]

    operations = [migrations.RunPython(add_client, remove_client)]
