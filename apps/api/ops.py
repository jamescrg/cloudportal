"""POST /api/v1/ops: the changes an app queued, applied in order.

Each op is applied once (AppliedOp, by the op's id for the user) in a
transaction of its own: its record is made first, so a second request with
the same op waits on the first and is then answered from the record. A
failed op is recorded too, and answered the same way again; its changes are
undone.

Changes to tasks go through the site's own task form and save step
(apps.tasks.views.save_task_form), filled in as the task dialog would be
with only the asked-for fields changed, as Claude's connector does
(apps.connector.tools), so a recurring task, its notifications and its
template behave as when the change is made on the site. Who may change
what is as on the site: a user's own tasks and any in a task folder they
own or are an editor of; only a folder's owner renames or deletes it, and
an editor deleting it leaves it.
"""

import uuid
from datetime import date, datetime, time

from django.db import IntegrityError, transaction

from apps.api.models import AppliedOp
from apps.api.sync import reachable_tasks
from apps.common.models import is_zone, zone_or_default
from apps.connector.tools import _errors, _form_data
from apps.folders.folders import get_accessible_folder_ids
from apps.folders.models import Folder
from apps.tasks import reminders as task_reminders
from apps.tasks.forms import TaskForm, TaskReminderForm
from apps.tasks.models import Task
from apps.tasks.views import complete_task, save_task_form

MAX_OPS = 200
MAX_REMINDERS = 20
REPEATS = ("daily", "weekdays", "weekly", "monthly", "monthly_weekday", "yearly")
TASK_FIELDS = {
    "title",
    "folder_id",
    "due_date",
    "due_time",
    "time_zone",
    "priority",
    "archived",
    "repeat",
}


class OpError(Exception):
    """An op that can't be applied: gone, invalid or forbidden."""

    def __init__(self, error, message):
        super().__init__(message)
        self.error = error
        self.message = message


def invalid(message):
    return OpError("invalid", message)


# --- reading values ----------------------------------------------------------


def _date(value, name):
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise invalid(f"{name} must be a date written YYYY-MM-DD.")


def _time(value, name):
    if value is None:
        return None
    try:
        if len(value) != 5:
            raise ValueError
        return time.fromisoformat(value)
    except (TypeError, ValueError):
        raise invalid(f"{name} must be a 24-hour time written HH:MM.")


def _int(value, name):
    if isinstance(value, bool) or not isinstance(value, int):
        raise invalid(f"{name} must be a whole number.")
    return value


def _name(op):
    name = op.get("name")
    if not isinstance(name, str) or not name.strip():
        raise invalid("name is required.")
    name = name.strip()
    if len(name) > 50:
        raise invalid("name can be at most 50 characters.")
    return name


# --- what an op names --------------------------------------------------------


def _resolve(user, value, kind, name):
    """The id an op names: the server's own, or "op:<uuid>", the op that
    made it."""
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str) and value.startswith("op:"):
        try:
            op_id = uuid.UUID(value[3:])
        except ValueError:
            raise invalid(f"{name} must be an id or op:<uuid>.")
        record = AppliedOp.objects.filter(user=user, op_id=op_id).first()
        made = record.result.get(f"{kind}_id") if record else None
        if made is None:
            raise OpError("gone", f"No {kind} was made by {value}.")
        return made
    raise invalid(f"{name} must be an id or op:<uuid>.")


def _task(user, op):
    task_id = _resolve(user, op.get("task"), "task", "task")
    folder_ids = get_accessible_folder_ids(user, "tasks")
    task = (
        reachable_tasks(user, folder_ids)
        .select_related("parent_task")
        .filter(pk=task_id)
        .first()
    )
    if task is None:
        raise OpError("gone", f"There is no task {task_id}.")
    return task


def _folder(user, value, name="folder"):
    folder_id = _resolve(user, value, "folder", name)
    if folder_id not in get_accessible_folder_ids(user, "tasks"):
        raise OpError("gone", f"There is no task folder {folder_id}.")
    return Folder.objects.get(pk=folder_id)


# --- tasks -------------------------------------------------------------------


def _repeat_changes(value):
    """The Repeat fields of the task form for a Repeat, or none."""
    if value is None:
        return {"repeat": "", "ends": "never", "until": "", "count": ""}
    if not isinstance(value, dict):
        raise invalid("repeat must be an object or null.")
    repeat = value.get("repeat")
    if repeat not in REPEATS:
        raise invalid("repeat.repeat must be one of " + ", ".join(REPEATS) + ".")
    interval = value.get("interval", 1)
    interval = 1 if interval is None else _int(interval, "repeat.interval")
    weekdays = value.get("weekdays") or []
    if not isinstance(weekdays, list) or any(
        isinstance(d, bool) or not isinstance(d, int) or not 0 <= d <= 6
        for d in weekdays
    ):
        raise invalid("repeat.weekdays must be a list of days, Monday 0 to Sunday 6.")
    ends = value.get("ends") or "never"
    if ends not in ("never", "on", "after"):
        raise invalid("repeat.ends must be never, on or after.")
    until = _date(value.get("until"), "repeat.until")
    count = value.get("count")
    if count is not None:
        count = _int(count, "repeat.count")
    return {
        "repeat": repeat,
        "interval": str(interval),
        "weekdays": [str(d) for d in weekdays],
        "ends": ends,
        "until": until.isoformat() if until else "",
        "count": "" if count is None else str(count),
    }


def _due_changes(task, user, fields):
    """The task form's due date and time for what the op asks: the parts
    it names, the rest as the task has them, read in the zone it gives (or
    the task's), and given to the form where the user is, as the site's
    dialog has them. Clearing the date clears the time."""
    if "time_zone" in fields:
        zone = fields["time_zone"]
        if not isinstance(zone, str) or not is_zone(zone):
            raise invalid("time_zone must be a time zone name, as America/New_York.")
    else:
        zone = task.time_zone if task.pk else user.time_zone
    due_date = (
        _date(fields["due_date"], "due_date") if "due_date" in fields else task.due_date
    )
    if "due_time" in fields:
        due_time = _time(fields["due_time"], "due_time")
        if due_time is not None and due_date is None:
            raise invalid("due_time needs a due_date.")
    else:
        due_time = task.due_time
    if due_date is None:
        return {"due_date": "", "due_time": ""}
    if due_time is None:
        return {"due_date": due_date.isoformat(), "due_time": ""}
    moment = datetime.combine(due_date, due_time, tzinfo=zone_or_default(zone))
    local = moment.astimezone(zone_or_default(user.time_zone))
    return {"due_date": local.date().isoformat(), "due_time": hhmm(local.time())}


def hhmm(value):
    return value.strftime("%H:%M")


def _task_changes(user, task, fields):
    """The task dialog's fields an op asks to change, as it would post
    them."""
    if not isinstance(fields, dict):
        raise invalid("fields must be an object.")
    unknown = set(fields) - TASK_FIELDS
    if unknown:
        raise invalid("Unknown fields: " + ", ".join(sorted(unknown)) + ".")
    changes = {}
    if "title" in fields:
        title = fields["title"]
        if not isinstance(title, str) or not title.strip():
            raise invalid("title can't be empty.")
        changes["title"] = title.strip()
    if "folder_id" in fields:
        value = fields["folder_id"]
        changes["folder"] = "" if value is None else str(_folder(user, value).pk)
    if {"due_date", "due_time", "time_zone"} & set(fields):
        changes.update(_due_changes(task, user, fields))
    if "priority" in fields:
        priority = _int(fields["priority"], "priority")
        if not 1 <= priority <= 10:
            raise invalid("priority must be from 1 (highest) to 10 (lowest).")
        changes["priority"] = str(priority)
    if "archived" in fields:
        if not isinstance(fields["archived"], bool):
            raise invalid("archived must be true or false.")
        changes["archived"] = str(fields["archived"])
    if "repeat" in fields:
        changes.update(_repeat_changes(fields["repeat"]))
    return changes


def _save(task, user, data, old_status):
    form = TaskForm(data, instance=task, use_required_attribute=False)
    folders = Folder.objects.filter(id__in=get_accessible_folder_ids(user, "tasks"))
    if task.folder_id:
        # A task left in a folder the user has lost stays there unless moved
        folders = folders | Folder.objects.filter(pk=task.folder_id)
    form.fields["folder"].queryset = folders
    if not form.is_valid():
        raise invalid(_errors(form))
    return save_task_form(form, user, old_status)


def _opened(task, user):
    """What the task dialog, opened on the task, would post untouched."""
    opened = TaskForm(instance=task, initial=vars(task.in_zone(user.time_zone)))
    return _form_data(opened)


def task_create(user, op):
    fields = op.get("fields")
    if not isinstance(fields, dict) or not isinstance(fields.get("title"), str):
        raise invalid("fields.title is required.")
    task = Task(user=user)
    data = {
        "title": "",
        "folder": "",
        "due_date": "",
        "due_time": "",
        "priority": "5",
        "status": "0",
        "archived": "False",
        "repeat": "",
        "interval": "1",
        "ends": "never",
    }
    data.update(_task_changes(user, task, fields))
    task = _save(task, user, data, old_status=0)
    return {"task_id": task.pk}


def task_update(user, op):
    task = _task(user, op)
    data = _opened(task, user)
    data.update(_task_changes(user, task, op.get("fields")))
    _save(task, user, data, task.status)
    return {}


def task_complete(user, op):
    task = _task(user, op)
    done_on = _date(op.get("date"), "date")
    if task.status != 1:
        complete_task(task, user, day=done_on)
    return {}


def task_reopen(user, op):
    task = _task(user, op)
    if task.status == 1:
        data = _opened(task, user)
        data["status"] = "0"
        _save(task, user, data, old_status=1)
    return {}


def task_delete(user, op):
    try:
        task = _task(user, op)
    except OpError as error:
        if error.error == "gone":
            return {}
        raise
    task.delete()
    return {}


def task_set_reminders(user, op):
    task = _task(user, op)
    wanted = op.get("reminders")
    if not isinstance(wanted, list) or len(wanted) > MAX_REMINDERS:
        raise invalid(f"reminders must be a list of at most {MAX_REMINDERS}.")
    if wanted and task.due_date is None:
        raise invalid("Set a due date to add notifications.")
    timed = task.due_date is not None and task.due_time is not None
    cleaned = []
    for index, reminder in enumerate(wanted):
        if not isinstance(reminder, dict):
            raise invalid(f"reminders[{index}] must be an object.")
        amount = reminder.get("amount")
        data = {
            "channel": reminder.get("channel") or "",
            "amount": "" if amount is None else str(_int(amount, "amount")),
            "unit": reminder.get("unit") or "",
            "time": reminder.get("time") or "",
        }
        if data["time"]:
            _time(data["time"], f"reminders[{index}].time")
        form = TaskReminderForm(data, task=task, timed=timed)
        if not form.is_valid():
            raise invalid(f"reminders[{index}]: " + _errors(form))
        cleaned.append(form.cleaned_data)

    for reminder in list(task.reminders.all()):
        task_reminders.remove_reminder(task, reminder.pk)
    for data in cleaned:
        task_reminders.add_reminder(
            task, data["amount"], data["unit"], data["time"], data["channel"]
        )
    return {}


def tasks_archive_completed(user, op):
    """The list's Archive button for completed tasks: all of the user's, the
    Inbox's, or a folder's (everyone's in it), as on the site."""
    scope = op.get("scope")
    if scope == "all":
        tasks = Task.objects.filter(user=user, status=1)
    elif scope == "inbox":
        tasks = Task.objects.filter(user=user, folder__isnull=True, status=1)
    else:
        tasks = Task.objects.filter(folder=_folder(user, scope, "scope"), status=1)
    tasks.update(archived=True)
    return {}


# --- folders -----------------------------------------------------------------


def folder_create(user, op):
    folder = Folder.objects.create(user=user, page="tasks", name=_name(op))
    return {"folder_id": folder.pk}


def folder_rename(user, op):
    folder = _folder(user, op.get("folder"))
    name = _name(op)
    if folder.user_id != user.pk:
        raise OpError("forbidden", "Only the folder's owner can rename it.")
    folder.name = name
    folder.save()
    return {}


def folder_delete(user, op):
    """As the site's Delete: the owner deletes the folder (its tasks go to
    their owners' Inboxes); anyone else it is shared with leaves it."""
    try:
        folder = _folder(user, op.get("folder"))
    except OpError as error:
        if error.error == "gone":
            return {}
        raise
    if folder.user_id == user.pk:
        folder.delete()
    else:
        folder.editors.remove(user)
    if user.tasks_folder == folder.pk:
        user.tasks_folder = 0
        user.save(update_fields=["tasks_folder"])
    return {}


HANDLERS = {
    "task.create": task_create,
    "task.update": task_update,
    "task.complete": task_complete,
    "task.reopen": task_reopen,
    "task.delete": task_delete,
    "task.set_reminders": task_set_reminders,
    "tasks.archive_completed": tasks_archive_completed,
    "folder.create": folder_create,
    "folder.rename": folder_rename,
    "folder.delete": folder_delete,
}


# --- applying ----------------------------------------------------------------


def _run(user, op):
    handler = HANDLERS.get(op.get("type"))
    if handler is None:
        raise invalid(f"Unknown op type {op.get('type')!r}.")
    return handler(user, op)


def apply(user, op):
    """Apply one op, once: its result, with its id."""
    raw_id = op.get("id")
    try:
        op_id = uuid.UUID(raw_id)
    except (TypeError, ValueError, AttributeError):
        return {
            "id": raw_id,
            "ok": False,
            "error": "invalid",
            "message": "The op's id must be a UUID.",
        }

    with transaction.atomic():
        try:
            with transaction.atomic():
                record = AppliedOp.objects.create(
                    user=user, op_id=op_id, type=str(op.get("type"))[:40]
                )
        except IntegrityError:
            # Applied before, or being applied by a request that has just
            # committed (this one waited on it)
            record = AppliedOp.objects.get(user=user, op_id=op_id)
            return {"id": raw_id, **record.result}

        try:
            with transaction.atomic():
                result = {"ok": True, **_run(user, op)}
        except OpError as error:
            result = {"ok": False, "error": error.error, "message": error.message}
        record.result = result
        record.save(update_fields=["result"])
    return {"id": raw_id, **result}
