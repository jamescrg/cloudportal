"""The scheduled jobs, run by the Django-Q cluster (manage.py qcluster).

Every job is defined here once. setup_schedules writes them to Django-Q's
Schedule table, creating or updating each by name, so running it on every
deploy keeps the table in step with this list.
"""

from dataclasses import dataclass

from croniter import croniter
from django.utils import timezone
from django_q.models import Schedule


@dataclass(frozen=True)
class ScheduleSpec:
    name: str
    func: str
    cron: str
    description: str = ""


def schedule_specs():
    return (
        ScheduleSpec(
            "event-reminders",
            "apps.calendar.reminders.send_due",
            "* * * * *",
            description="Sends the event notifications that have come due.",
        ),
        ScheduleSpec(
            "task-reminders",
            "apps.tasks.reminders.send_all",
            "* * * * *",
            description="Sends the task notifications that have come due.",
        ),
        ScheduleSpec(
            "recurring-tasks",
            "apps.tasks.recurring.create_instances",
            "0 1 * * *",
            description=(
                "Gives any recurring task left without an open instance (one "
                "completed in bulk, say, or deleted) its next one, due on the "
                "rule's next day."
            ),
        ),
        ScheduleSpec(
            "calendar-sync",
            "apps.calendar.sync.sync_all",
            "*/5 * * * *",
            description=(
                "Two-way Google Calendar sync for every user who has it on: "
                "pushes pending local changes and deletions, then pulls "
                "changes from Google."
            ),
        ),
        ScheduleSpec(
            "extend-event-series",
            "apps.calendar.recurrence.extend_all",
            "0 2 * * *",
            description=(
                "Tops up every repeating event's occurrences to a year ahead, "
                "as the days pass."
            ),
        ),
        ScheduleSpec(
            "site-icons",
            "apps.favorites.site_icons.ensure_all",
            "30 3 * * *",
            description=(
                "Queues a fetch of the site icon of every host the favorites "
                "point at that has none yet, had none found a week ago, or "
                "has one three months old."
            ),
        ),
    )


def install_schedules(names=None):
    """Create or update the schedules (all, or those named) and return
    (spec, created) pairs."""
    wanted = set(names) if names is not None else None
    local_now = timezone.localtime(timezone.now())
    results = []

    for spec in schedule_specs():
        if wanted is not None and spec.name not in wanted:
            continue
        _, created = Schedule.objects.update_or_create(
            name=spec.name,
            defaults={
                "func": spec.func,
                "schedule_type": Schedule.CRON,
                "cron": spec.cron,
                "repeats": -1,
                # A new or changed schedule waits for its next real slot
                # rather than firing as soon as the cluster starts
                "next_run": croniter(spec.cron, local_now).get_next(type(local_now)),
            },
        )
        results.append((spec, created))

    return results
