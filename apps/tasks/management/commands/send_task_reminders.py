"""
Send the task notifications that have come due.

The Django-Q cluster runs this every minute (the "task-reminders"
schedule in apps/management/schedules.py); this command runs it by hand.

A task is notified only when a notification was set on it.
"""

from django.core.management.base import BaseCommand

from apps.tasks import reminders


class Command(BaseCommand):
    help = "Send the task notifications that have come due"

    def handle(self, *args, **options):
        result = reminders.send_all()
        self.stdout.write(
            self.style.SUCCESS(
                f"Sent {result['sent']} notification(s), {result['errors']} error(s)"
            )
        )
