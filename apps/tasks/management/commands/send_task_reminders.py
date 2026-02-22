"""
Send email reminders for tasks with due dates.

Run every 15 minutes via cron:
    */15 * * * * cd /home/james/mh && /home/james/.venvs/mh/bin/python manage.py send_task_reminders
"""

from collections import defaultdict
from datetime import date, datetime

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.tasks.models import Task
from config.email import send_past_due_digest_email, send_task_reminder_email


class Command(BaseCommand):
    help = "Send email reminders for tasks with due dates"

    def handle(self, *args, **options):
        today = date.today()
        now = timezone.localtime()
        sent_count = 0
        error_count = 0

        # Pending, non-archived tasks with due dates, user has reminders enabled,
        # not already reminded today
        base_qs = (
            Task.objects.filter(
                status=0,
                archived=False,
                due_date__isnull=False,
                is_recurring=False,
                user__email_reminders=True,
            )
            .exclude(user__notification_email="", user__email="")
            .exclude(reminder_sent_date=today)
            .select_related("user", "folder")
        )

        # Category 1: Overdue (due_date < today) — one digest per user
        overdue_by_user = defaultdict(list)
        for task in base_qs.filter(due_date__lt=today):
            overdue_by_user[task.user].append(task)

        for user, tasks in overdue_by_user.items():
            result = send_past_due_digest_email(user, tasks)
            if result["success"]:
                for task in tasks:
                    task.reminder_sent_date = today
                    task.save(update_fields=["reminder_sent_date"])
                sent_count += 1
            else:
                error_count += 1

        # Category 2: Due today, no time set
        for task in base_qs.filter(due_date=today, due_time__isnull=True):
            sent_count, error_count = self._send(
                task, "due_today", today, sent_count, error_count
            )

        # Category 3: Due today with time, within ~1 hour
        for task in base_qs.filter(due_date=today, due_time__isnull=False):
            due_dt = timezone.make_aware(datetime.combine(today, task.due_time))
            minutes_until = (due_dt - now).total_seconds() / 60
            if 0 <= minutes_until <= 75:
                sent_count, error_count = self._send(
                    task, "due_soon", today, sent_count, error_count
                )

        self.stdout.write(
            self.style.SUCCESS(f"Sent {sent_count} reminder(s), {error_count} error(s)")
        )

    def _send(self, task, reminder_type, today, sent_count, error_count):
        result = send_task_reminder_email(task.user, task, reminder_type)
        if result["success"]:
            task.reminder_sent_date = today
            task.save(update_fields=["reminder_sent_date"])
            sent_count += 1
        else:
            error_count += 1
        return sent_count, error_count
