"""GET /api/v1/sync: the user's task folders and tasks, all of them or
what changed since a cursor.

A cursor is the moment a sync began, signed so it is the server's own.
The next sync sends what changed from a little before it (OVERLAP): a
change is stamped when it is made, and one still in a transaction when a
sync is answered commits with an earlier stamp than the cursor. Anything
sent twice the app upserts again; nothing is missed. A cursor older than
the tombstones kept (apps.api.tracking.RETENTION), another user's, or not
the server's gets the full snapshot.

What a user reaches is what the site shows them: their own tasks and the
tasks in the task folders they own or are an editor of (apps.tasks.views
_task_for); recurring templates are never sent.
"""

from datetime import UTC, datetime, timedelta

from django.core import signing
from django.db.models import Q
from django.utils import timezone

from apps.api.models import Tombstone
from apps.api.tracking import RETENTION
from apps.common.recurrence import describe, form_initial
from apps.folders.folders import get_accessible_folder_ids
from apps.folders.models import Folder
from apps.tasks.models import Task

OVERLAP = timedelta(minutes=10)
CURSOR_SALT = "apps.api.sync.cursor"


# --- values ------------------------------------------------------------------


def timestamp(value):
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ") if value else None


def day(value):
    return value.isoformat() if value else None


def hhmm(value):
    return value.strftime("%H:%M") if value else None


def display_name(user):
    return user.get_full_name() or user.username


# --- cursors -----------------------------------------------------------------


def make_cursor(user, moment):
    return signing.dumps({"u": user.pk, "t": moment.isoformat()}, salt=CURSOR_SALT)


def read_cursor(user, cursor, now=None):
    """The moment a cursor was made, or None for one the server no longer
    honours."""
    now = now or timezone.now()
    try:
        data = signing.loads(cursor, salt=CURSOR_SALT)
        moment = datetime.fromisoformat(data["t"])
    except (signing.BadSignature, KeyError, TypeError, ValueError):
        return None
    if data.get("u") != user.pk or moment.tzinfo is None:
        return None
    # Tombstones go after RETENTION; a cursor needs every one since a
    # little before it, with a day to spare
    if moment - OVERLAP < now - RETENTION + timedelta(days=1):
        return None
    return moment


# --- what is sent ------------------------------------------------------------


def reachable_tasks(user, folder_ids):
    """Every task the user can reach, but recurring templates."""
    return Task.objects.filter(
        Q(user=user) | Q(folder_id__in=folder_ids), is_recurring=False
    )


def folder_data(folder, user):
    editors = list(folder.editors.all())
    people = [folder.user, *editors]
    return {
        "id": folder.id,
        "name": folder.name,
        "mine": folder.user_id == user.pk,
        "shared": bool(editors),
        "shared_with": [display_name(p) for p in people if p.pk != user.pk],
        "owner": display_name(folder.user),
        "updated_at": timestamp(folder.updated_at),
    }


def repeat_data(rule):
    """A rule as the site's task form has it (form_initial)."""
    initial = form_initial(rule)
    return {
        "repeat": initial["repeat"],
        "interval": initial["interval"],
        "weekdays": (
            [int(d) for d in initial["weekdays"]]
            if initial["repeat"] == "weekly"
            else []
        ),
        "ends": initial["ends"],
        "until": day(initial["until"]),
        "count": initial["count"],
    }


def reminder_data(reminder, task):
    # A time of day only for a task with a date and no time of its own
    all_day = task.due_date is not None and task.due_time is None
    return {
        "id": reminder.id,
        "channel": reminder.channel,
        "amount": reminder.amount,
        "unit": reminder.unit,
        "time": hhmm(reminder.time) if all_day else None,
    }


def task_data(task, user, folder_ids):
    template = task.parent_task
    rule = template.rule if template is not None else None
    return {
        "id": task.id,
        "title": task.title,
        # The user's own task in a folder they no longer reach is in their
        # Inbox, as the site lists it
        "folder_id": task.folder_id if task.folder_id in folder_ids else None,
        "mine": task.user_id == user.pk,
        "done": task.status == 1,
        "completed_date": day(task.completed_date),
        "priority": task.priority,
        "archived": task.archived,
        "due_date": day(task.due_date),
        "due_time": hhmm(task.due_time),
        "time_zone": task.time_zone,
        "repeat": repeat_data(rule) if rule else None,
        "repeat_summary": describe(rule) if rule else "",
        "reminders": [reminder_data(r, task) for r in task.reminders.all()],
        "created_at": timestamp(task.created_at),
        "updated_at": timestamp(task.updated_at),
    }


def user_data(user):
    return {
        "id": user.pk,
        "name": display_name(user),
        "email": user.email,
        "time_zone": user.time_zone,
        "notify_by": user.notify_by,
    }


def snapshot(user, cursor=None):
    """The answer to GET /sync: everything (no cursor, or one not
    honoured) or what changed since the cursor."""
    started = timezone.now()
    since = read_cursor(user, cursor, started) if cursor else None
    full = since is None

    folder_ids = get_accessible_folder_ids(user, "tasks")
    folders = (
        Folder.objects.filter(id__in=folder_ids)
        .select_related("user")
        .prefetch_related("editors")
        .order_by("name", "id")
    )
    tasks = (
        reachable_tasks(user, folder_ids)
        .select_related("parent_task")
        .prefetch_related("reminders")
        .order_by("id")
    )
    deleted = {"tasks": [], "folders": []}
    if full:
        tasks = tasks.filter(archived=False)
    else:
        after = since - OVERLAP
        folders = folders.filter(updated_at__gte=after)
        tasks = tasks.filter(updated_at__gte=after)
        gone = Tombstone.objects.filter(
            deleted_at__gte=after, users__contains=[user.pk]
        )
        task_ids = set(
            gone.filter(kind=Tombstone.TASK).values_list("object_id", flat=True)
        )
        # One moved away and back again, or into another of their folders,
        # is not gone
        task_ids -= set(
            reachable_tasks(user, folder_ids)
            .filter(pk__in=task_ids)
            .values_list("id", flat=True)
        )
        folder_gone = set(
            gone.filter(kind=Tombstone.FOLDER).values_list("object_id", flat=True)
        )
        deleted = {
            "tasks": sorted(task_ids),
            "folders": sorted(folder_gone - folder_ids),
        }

    return {
        "cursor": make_cursor(user, started),
        "full": full,
        "user": user_data(user),
        "folder_ids": sorted(folder_ids),
        "folders": [folder_data(f, user) for f in folders],
        "tasks": [task_data(t, user, folder_ids) for t in tasks],
        "deleted": deleted,
    }
