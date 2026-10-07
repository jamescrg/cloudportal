"""
Generate task instances from recurring templates.

The Django-Q cluster runs this daily (the "recurring-tasks" schedule in
apps/management/schedules.py); this command runs it by hand.
"""

from django.core.management.base import BaseCommand

from apps.tasks import recurring


class Command(BaseCommand):
    help = "Generate task instances from recurring templates"

    def handle(self, *args, **options):
        created_count = recurring.create_instances()
        self.stdout.write(
            self.style.SUCCESS(f"Created {created_count} recurring task(s)")
        )
