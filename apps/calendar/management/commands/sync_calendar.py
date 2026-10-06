from datetime import datetime

from django.core.management.base import BaseCommand

from accounts.models import CustomUser
from apps.calendar import sync


class Command(BaseCommand):
    help = "Sync events with Google Calendar (two-way) for every connected user"

    def handle(self, *args, **options):
        self.stdout.write("Starting Google Calendar sync...")

        users = (
            CustomUser.objects.filter(is_active=True)
            .exclude(google_credentials__isnull=True)
            .exclude(google_credentials="")
        )

        for user in users:
            try:
                # Push local changes + drain queued deletions first, so local
                # removals reach Google before the pull (which would otherwise
                # re-create them) and any previously failed pushes get retried.
                result = sync.scheduled_sync(user)
                self.stdout.write(f"{user}: reconciled {result['reconciled']}")
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"✗ Sync failed for {user}: {e}"))
                raise

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.stdout.write(
            self.style.SUCCESS(f"✓ Google Calendar sync completed at {timestamp}")
        )
