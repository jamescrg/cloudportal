"""The CloudPortal Weather Android app, as an OAuth client of the site, as
the tasks app is (0002): public, signing in by authorization code with
PKCE, and returning to the app by its own URI scheme. A client of its own,
so that being signed in to the weather is never taken for the tasks app
being connected."""

from django.db import migrations

CLIENT_ID = "cloudportal-weather-android"


def add_client(apps, schema_editor):
    Application = apps.get_model("oauth2_provider", "Application")
    Application.objects.get_or_create(
        client_id=CLIENT_ID,
        defaults={
            "name": "CloudPortal Weather for Android",
            "client_type": "public",
            "authorization_grant_type": "authorization-code",
            "redirect_uris": "net.cloudportal.weather:/oauth",
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
        ("api", "0002_android_client"),
        ("oauth2_provider", "0022_refreshtoken_token_family_index"),
    ]

    operations = [migrations.RunPython(add_client, remove_client)]
