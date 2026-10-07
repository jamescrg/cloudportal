"""
Make repeating events' occurrences a year ahead.

A repeating event's occurrences are made a year ahead when it is saved;
the Django-Q cluster keeps that year topped up daily (the
"extend-event-series" schedule in apps/management/schedules.py). This
command runs the same job by hand.
"""

from django.core.management.base import BaseCommand

from apps.calendar import recurrence


class Command(BaseCommand):
    help = "Make repeating events' occurrences a year ahead"

    def handle(self, *args, **options):
        made = recurrence.extend_all()
        self.stdout.write(self.style.SUCCESS(f"Made {made} occurrence(s)"))
