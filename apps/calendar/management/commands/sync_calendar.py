"""
Sync events with Google Calendar, both ways, for every connected user.

The Django-Q cluster runs this every 5 minutes (the "calendar-sync"
schedule in apps/management/schedules.py); this command runs it by hand.
"""

from django.core.management.base import BaseCommand

from apps.calendar import sync


class Command(BaseCommand):
    help = "Sync events with Google Calendar (two-way) for every connected user"

    def handle(self, *args, **options):
        result = sync.sync_all()
        self.stdout.write(
            self.style.SUCCESS(
                f"Google Calendar sync: {result['synced']} user(s) synced, "
                f"{result['failed']} failed"
            )
        )
