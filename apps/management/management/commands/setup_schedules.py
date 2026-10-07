"""
Create or update the Django-Q schedules (apps/management/schedules.py).

Safe to run on every deploy, after migrate:
    /path/to/.venv/bin/python /path/to/manage.py setup_schedules
"""

from django.core.management.base import BaseCommand

from apps.management.schedules import install_schedules


class Command(BaseCommand):
    help = "Create or update every scheduled job run by the Django-Q cluster"

    def handle(self, *args, **options):
        results = install_schedules()
        for spec, created in results:
            action = "Created" if created else "Updated"
            self.stdout.write(
                self.style.SUCCESS(f"{action} {spec.name} (cron: {spec.cron})")
            )
        self.stdout.write(self.style.SUCCESS(f"Configured {len(results)} schedule(s)."))
