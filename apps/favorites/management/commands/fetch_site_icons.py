from django.core.management.base import BaseCommand

from apps.favorites import site_icons


class Command(BaseCommand):
    help = (
        "Queue a fetch, on the worker, of the icon of every host a favorite "
        "points at that has no icon yet or a stale one."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--retry-missing",
            action="store_true",
            help="Also every host whose last fetch found nothing, due or not.",
        )

    def handle(self, *args, **options):
        queued = site_icons.ensure_all(retry_missing=options["retry_missing"])
        self.stdout.write(self.style.SUCCESS(f"Queued {queued} icon fetch(es)."))
