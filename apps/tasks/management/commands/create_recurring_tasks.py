"""
Management command to generate task instances from recurring templates.

Run daily via cron:
    0 1 * * * cd /home/james/mh && /home/james/.venvs/mh/bin/python manage.py create_recurring_tasks
"""

from datetime import date

from django.core.management.base import BaseCommand

from apps.tasks.models import Task


class Command(BaseCommand):
    help = "Generate task instances from recurring templates"

    def handle(self, *args, **options):
        today = date.today()
        created_count = 0

        recurring_tasks = Task.objects.filter(is_recurring=True, archived=False)

        # Clean up accumulated pending instances: keep only the most recent per parent
        for template in recurring_tasks:
            pending = Task.objects.filter(
                parent_task=template, status=0, archived=False
            ).order_by("-due_date")
            stale_ids = list(pending.values_list("id", flat=True)[1:])
            if stale_ids:
                Task.objects.filter(id__in=stale_ids).delete()

        for template in recurring_tasks:
            if self.should_generate(template, today):
                self.create_instance(template, today)
                template.last_generated = today
                template.save(update_fields=["last_generated"])
                created_count += 1

        self.stdout.write(
            self.style.SUCCESS(f"Created {created_count} recurring task(s)")
        )

    def should_generate(self, template, today):
        """Check if a new instance should be generated today."""
        if Task.objects.filter(parent_task=template, status=0, archived=False).exists():
            return False

        last = template.last_generated

        if template.recurrence_type == "daily":
            # Generate if we haven't generated today
            return last is None or last < today

        elif template.recurrence_type == "weekly":
            # Generate if today matches the weekday and not already generated this week
            if today.weekday() != template.recurrence_day:
                return False
            if last is None:
                return True
            # Check if last_generated was in a previous week
            days_since = (today - last).days
            return days_since >= 7

        elif template.recurrence_type == "monthly":
            # Generate if today matches the day of month and not already generated this month
            if today.day != template.recurrence_day:
                return False
            if last is None:
                return True
            # Check if last_generated was in a previous month
            return last.year < today.year or last.month < today.month

        elif template.recurrence_type == "yearly":
            # Generate if today matches day and month, not already generated this year
            if today.day != template.recurrence_day:
                return False
            if today.month != template.recurrence_month:
                return False
            if last is None:
                return True
            return last.year < today.year

        return False

    def create_instance(self, template, today):
        """Create a new task instance from a recurring template."""
        Task.objects.create(
            user=template.user,
            folder=template.folder,
            title=template.title,
            priority=template.priority,
            status=0,
            due_date=today,
            due_time=template.due_time,
            parent_task=template,
        )
