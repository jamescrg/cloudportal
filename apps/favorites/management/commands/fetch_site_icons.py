from django.core.management.base import BaseCommand

from apps.favorites import site_icons


class Command(BaseCommand):
    help = (
        "Queue a fetch, on the worker, of the icon of every host a favorite "
        "points at that has no icon yet or a stale one."
    )

    def handle(self, *args, **options):
        queued = site_icons.ensure_all()
        self.stdout.write(self.style.SUCCESS(f"Queued {queued} icon fetch(es)."))
