"""
Send task notifications, and the daily past-due digest.

The Django-Q cluster runs this every 5 minutes (the "task-reminders"
schedule in apps/management/schedules.py); this command runs it by hand.

A task is notified only when a notification was set on it. The digest of
past-due tasks goes once a day to users who turned Email Reminders on.
"""

from django.core.management.base import BaseCommand

from apps.tasks import reminders


class Command(BaseCommand):
    help = "Send task notifications and the daily past-due digest"

    def handle(self, *args, **options):
        result = reminders.send_all()
        self.stdout.write(
            self.style.SUCCESS(
                f"Sent {result['sent']} notification(s), {result['digests']} digest(s), "
                f"{result['errors']} error(s)"
            )
        )
