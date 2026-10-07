"""
Create or update the Django-Q schedules (apps/management/schedules.py).

Safe to run on every deploy, after migrate:
    /path/to/.venv/bin/python /path/to/manage.py setup_schedules

A machine that should run only some jobs (a dev machine that must not send
email, say) names them, and has any others it holds removed:
    manage.py setup_schedules --only extend-event-series
"""

from django.core.management.base import BaseCommand, CommandError
from django_q.models import Schedule

from apps.management.schedules import install_schedules, schedule_specs


class Command(BaseCommand):
    help = "Create or update every scheduled job run by the Django-Q cluster"

    def add_arguments(self, parser):
        parser.add_argument(
            "--only",
            nargs="+",
            metavar="NAME",
            help="Install only these schedules, and remove the others",
        )

    def handle(self, *args, only=None, **options):
        known = {spec.name for spec in schedule_specs()}
        if only:
            unknown = set(only) - known
            if unknown:
                raise CommandError(f"Unknown schedule(s): {', '.join(sorted(unknown))}")
            removed, _ = Schedule.objects.filter(name__in=known - set(only)).delete()
            if removed:
                self.stdout.write(f"Removed {removed} schedule(s) not named")

        results = install_schedules(only)
        for spec, created in results:
            action = "Created" if created else "Updated"
            self.stdout.write(
                self.style.SUCCESS(f"{action} {spec.name} (cron: {spec.cron})")
            )
        self.stdout.write(self.style.SUCCESS(f"Configured {len(results)} schedule(s)."))
