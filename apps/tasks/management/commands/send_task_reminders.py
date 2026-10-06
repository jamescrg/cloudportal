"""
Send task notifications, and the daily past-due digest.

Run every 5 minutes via cron:
    */5 * * * * /path/to/.venv/bin/python /path/to/manage.py send_task_reminders

A task is notified only when a notification was set on it. The digest of
past-due tasks goes once a day to users who turned Email Reminders on.
"""

from collections import defaultdict
from datetime import date

from django.core.management.base import BaseCommand

from apps.tasks import reminders
from apps.tasks.models import Task
from config.email import send_past_due_digest_email


class Command(BaseCommand):
    help = "Send task notifications and the past-due digest"

    def handle(self, *args, **options):
        today = date.today()

        sent, errors = reminders.send_due()

        # Past due (due_date < today): one digest per user, once a day
        overdue = (
            Task.objects.filter(
                status=0,
                archived=False,
                due_date__lt=today,
                is_recurring=False,
                user__email_reminders=True,
            )
            .exclude(user__notification_email="", user__email="")
            .exclude(reminder_sent_date=today)
            .select_related("user", "folder")
        )
        overdue_by_user = defaultdict(list)
        for task in overdue:
            overdue_by_user[task.user].append(task)

        digests = 0
        for user, tasks in overdue_by_user.items():
            result = send_past_due_digest_email(user, tasks)
            if result["success"]:
                for task in tasks:
                    task.reminder_sent_date = today
                    task.save(update_fields=["reminder_sent_date"])
                digests += 1
            else:
                errors += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Sent {sent} notification(s), {digests} digest(s), {errors} error(s)"
            )
        )
