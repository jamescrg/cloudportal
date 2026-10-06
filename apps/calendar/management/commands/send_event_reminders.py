"""
Send email notifications for calendar events.

Run every 5 minutes via cron:
    */5 * * * * /path/to/.venv/bin/python /path/to/manage.py send_event_reminders
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
