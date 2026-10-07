"""
Send email notifications for calendar events.

The Django-Q cluster runs this every 5 minutes (the "event-reminders"
schedule in apps/management/schedules.py); this command runs it by hand.
"""

from django.core.management.base import BaseCommand

from apps.calendar import reminders


class Command(BaseCommand):
    help = "Send email notifications for calendar events"

    def handle(self, *args, **options):
        sent, errors = reminders.send_due()
        self.stdout.write(
            self.style.SUCCESS(f"Sent {sent} notification(s), {errors} error(s)")
        )
