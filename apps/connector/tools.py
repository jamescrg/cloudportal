"""The tools Claude's connector offers: the user's tasks and calendar.

Changes go through the site's own forms and save steps (the task and event
dialogs'), filled in as the dialog would be with only the asked-for fields
changed, so a repeating task or event, its notifications, its guests and
its Google copy behave just as when the change is made on the site.
Nothing here deletes.

Dates are YYYY-MM-DD and times 24-hour HH:MM, both where the user is (their
time zone in Settings), as the site shows them.
"""

from datetime import date, datetime, time, timedelta

from django.db.models import Q

from apps.calendar import invitations, recurrence
from apps.calendar.forms import EventForm
from apps.calendar.models import Event
from apps.calendar.views import _save_event, save_event_edit
from apps.common.models import zone_or_default
from apps.folders.folders import get_accessible_folder_ids
from apps.folders.models import Folder
from apps.tasks.forms import TaskForm
from apps.tasks.models import Task
from apps.tasks.priority import LEVELS, level_for
from apps.tasks.views import complete_task as mark_done, save_task_form

LIST_LIMIT = 200
PRIORITIES = [name for _, name, _, _, _ in LEVELS]


class ToolError(Exception):
    """A tool's call could not be carried out; the message goes back to
    Claude, which can correct the call or tell the user."""


# --- reading and writing values ---------------------------------------------


def _today(user):
    return datetime.now(zone_or_default(user.time_zone)).date()


def _date_arg(args, name):
    value = args.get(name)
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise ToolError(f"{name} must be a date written YYYY-MM-DD.")


def _int_arg(args, name):
    value = args.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ToolError(f"{name} must be a number.")
    try:
        return int(value)
    except ValueError:
        raise ToolError(f"{name} must be a number.")


def _as_data(value):
    """A form's initial value as the text a dialog would post."""
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return [_as_data(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, time):
        return value.strftime("%H:%M")
    if hasattr(value, "pk"):
        return str(value.pk)
    return str(value)


def _form_data(form):
    """What an unbound form, opened on its object, would post untouched."""
    return {name: _as_data(form[name].value()) for name in form.fields}


def _errors(form):
    """A form's errors as one line for Claude."""
    parts = []
    for field, errors in form.errors.items():
        label = "" if field == "__all__" else f"{field}: "
        parts.append(label + " ".join(errors))
    return "; ".join(parts) or "The change could not be saved."


def _hhmm(value):
    return value.strftime("%H:%M") if value else None


def _iso(value):
    return value.isoformat() if value else None


# --- tasks -------------------------------------------------------------------


def _task_folders(user):
    return Folder.objects.filter(
        id__in=get_accessible_folder_ids(user, "tasks")
    ).order_by("name")


def _task_info(task, user):
    shown = task.in_zone(user.time_zone)
    return {
        "id": task.id,
        "title": task.title,
        "folder": task.folder.name if task.folder else "Inbox",
        "folder_id": task.folder_id,
        "due_date": _iso(shown.due_date),
        "due_time": _hhmm(shown.due_time),
        "priority": level_for(task.priority)["name"],
        "done": task.status == 1,
        "completed_date": _iso(task.completed_date),
        "archived": task.archived,
        "repeats": task.parent_task_id is not None,
    }


def _own_task(user, args):
    task_id = _int_arg(args, "task_id")
    task = (
        Task.objects.select_related("folder")
        .filter(pk=task_id, user=user, is_recurring=False)
        .first()
    )
    if task is None:
        raise ToolError(f"There is no task {task_id}.")
    return task


def _task_changes(user, args):
    """The task dialog's fields an edit asks to change, as it would post
    them."""
    changes = {}
    if "title" in args:
        title = str(args["title"] or "").strip()
        if not title:
            raise ToolError("title can't be empty.")
        changes["title"] = title
    if "folder_id" in args:
        folder_id = args["folder_id"]
        if folder_id in (None, "", "inbox"):
            changes["folder"] = ""
        else:
            folder_id = _int_arg(args, "folder_id")
            if not _task_folders(user).filter(pk=folder_id).exists():
                raise ToolError(f"There is no task folder {folder_id}.")
            changes["folder"] = str(folder_id)
    if "due_date" in args:
        due = _date_arg(args, "due_date")
        changes["due_date"] = _iso(due) or ""
        if due is None:
            changes["due_time"] = ""
    if "due_time" in args:
        changes["due_time"] = str(args["due_time"] or "")
    if "priority" in args:
        wanted = str(args["priority"] or "").strip().lower()
        for slug, name, _, value, _ in LEVELS:
            if wanted in (slug, name.lower()):
                changes["priority"] = str(value)
                break
        else:
            raise ToolError("priority must be one of " + ", ".join(PRIORITIES) + ".")
    return changes


def _save_task(task, user, data, old_status):
    form = TaskForm(data, instance=task, use_required_attribute=False)
    form.fields["folder"].queryset = _task_folders(user)
    if not form.is_valid():
        raise ToolError(_errors(form))
    return save_task_form(form, user, old_status)


def list_task_folders(user, args):
    folders = [{"id": f.id, "name": f.name} for f in _task_folders(user)]
    return {
        "folders": folders,
        "note": "A task in no folder is in the Inbox (folder_id null).",
    }


def find_tasks(user, args):
    status = args.get("status") or "open"
    if status not in ("open", "done", "all"):
        raise ToolError("status must be open, done or all.")
    tasks = Task.objects.filter(user=user, is_recurring=False).select_related("folder")
    if not args.get("include_archived"):
        tasks = tasks.filter(archived=False)
    if status == "open":
        tasks = tasks.exclude(status=1)
    elif status == "done":
        tasks = tasks.filter(status=1)
    if "folder_id" in args:
        folder_id = args["folder_id"]
        if folder_id in (None, "", "inbox"):
            tasks = tasks.filter(folder__isnull=True)
        else:
            tasks = tasks.filter(folder_id=_int_arg(args, "folder_id"))
    due_from = _date_arg(args, "due_from")
    due_to = _date_arg(args, "due_to")
    if due_from:
        tasks = tasks.filter(due_date__gte=due_from)
    if due_to:
        tasks = tasks.filter(due_date__lte=due_to)
    if args.get("text"):
        tasks = tasks.filter(title__icontains=str(args["text"]))

    limit = min(_int_arg(args, "limit") if "limit" in args else 50, LIST_LIMIT)
    tasks = tasks.order_by(
        "status", "due_date", "due_time", "priority", "id"
    )  # undated last on PostgreSQL
    total = tasks.count()
    found = [_task_info(task, user) for task in tasks[: max(limit, 1)]]
    return {"tasks": found, "total": total, "shown": len(found)}


def create_task(user, args):
    title = str(args.get("title") or "").strip()
    if not title:
        raise ToolError("title is required.")
    task = Task(user=user)
    data = {
        "title": title,
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
    data.update(_task_changes(user, args))
    task = _save_task(task, user, data, old_status=0)
    return {"created": _task_info(task, user)}


def update_task(user, args):
    task = _own_task(user, args)
    old_status = task.status
    opened = TaskForm(instance=task, initial=vars(task.in_zone(user.time_zone)))
    data = _form_data(opened)
    data.update(_task_changes(user, args))
    task = _save_task(task, user, data, old_status)
    return {"updated": _task_info(task, user)}


def complete_task(user, args):
    task = _own_task(user, args)
    was_done = task.status == 1
    if not was_done:
        mark_done(task, user)
    result = {"completed": _task_info(task, user)}
    if was_done:
        result["note"] = "The task was already done."
    # A repeating task's next instance comes on when one is done
    if task.parent_task_id:
        upcoming = (
            Task.objects.filter(parent_task_id=task.parent_task_id, status=0)
            .exclude(pk=task.pk)
            .order_by("due_date")
            .first()
        )
        if upcoming:
            result["next"] = _task_info(upcoming, user)
    return result


def reopen_task(user, args):
    task = _own_task(user, args)
    if task.status != 1:
        return {"reopened": _task_info(task, user), "note": "The task was open."}
    opened = TaskForm(instance=task, initial=vars(task.in_zone(user.time_zone)))
    data = _form_data(opened)
    data["status"] = "0"
    task = _save_task(task, user, data, old_status=1)
    return {"reopened": _task_info(task, user)}


# --- calendar ----------------------------------------------------------------


def _event_info(event, user):
    shown = event.in_zone(user.time_zone)
    return {
        "id": event.id,
        "title": event.description,
        "date": _iso(shown.date),
        "end_date": _iso(shown.end_date),
        "start_time": _hhmm(shown.start_time),
        "end_time": _hhmm(shown.end_time),
        "all_day": shown.start_time is None,
        "location": event.location or None,
        "repeats": event.series_id is not None,
    }


def _event_changes(args):
    """The event dialog's fields an edit asks to change, as it would post
    them."""
    changes = {}
    if "title" in args:
        changes["description"] = str(args["title"] or "").strip()
    for name in ("date", "end_date"):
        if name in args:
            changes[name] = _iso(_date_arg(args, name)) or ""
    for name in ("start_time", "end_time"):
        if name in args:
            changes[name] = str(args[name] or "")
    # Without a start it is all day, so it has no end time either
    if "start_time" in args and not args["start_time"]:
        changes["end_time"] = ""
    if "location" in args:
        changes["location"] = str(args["location"] or "")
    return changes


def _sync_note(result):
    return {
        "ok": "Saved, and copied to Google Calendar.",
        "failed": "Saved; the copy to Google Calendar failed and will be retried.",
    }.get(result)


def list_events(user, args):
    first = _date_arg(args, "start") or _today(user)
    last = _date_arg(args, "end") or first + timedelta(days=13)
    if last < first:
        raise ToolError("end must be on or after start.")
    if (last - first).days > 366:
        raise ToolError("Ask for a year or less at a time.")
    # Repeating events are made a year ahead; a look further out makes them
    recurrence.extend_for(user, last + timedelta(days=1))
    # A day's margin each side for timed events whose day differs where
    # the user is; the days are checked as shown below
    events = (
        Event.objects.filter(user=user, date__lte=last + timedelta(days=1))
        .filter(
            Q(end_date__gte=first - timedelta(days=1))
            | Q(end_date=None, date__gte=first - timedelta(days=1))
        )
        .order_by("date", "start_time", "id")
    )
    if args.get("text"):
        events = events.filter(description__icontains=str(args["text"]))

    found = []
    for event in events:
        info = _event_info(event, user)
        start = date.fromisoformat(info["date"])
        end = date.fromisoformat(info["end_date"] or info["date"])
        if end >= first and start <= last:
            found.append(info)
    found.sort(key=lambda e: (e["date"], e["start_time"] or ""))
    shown = found[:LIST_LIMIT]
    return {
        "start": first.isoformat(),
        "end": last.isoformat(),
        "events": shown,
        "total": len(found),
    }


def create_event(user, args):
    data = {
        "description": "",
        "date": "",
        "end_date": "",
        "start_time": "",
        "end_time": "",
        "location": "",
        "repeat": "",
        "interval": "1",
        "ends": "never",
    }
    data.update(_event_changes(args))
    if not data["date"]:
        raise ToolError("date is required.")
    form = EventForm(data)
    if not form.is_valid():
        raise ToolError(_errors(form))
    result = _save_event(form, user)
    created = {"created": _event_info(form.instance, user)}
    note = _sync_note(result)
    if note:
        created["note"] = note
    return created


def update_event(user, args):
    event_id = _int_arg(args, "event_id")
    event = Event.objects.filter(pk=event_id, user=user).first()
    if event is None:
        raise ToolError(f"There is no event {event_id}.")
    series = event.series
    before = invitations.details(event)
    shown = event.in_zone(user.time_zone)
    if series is not None:
        initial = vars(shown) | recurrence.form_initial(series)
    else:
        initial = vars(shown) | {"weekdays": [str(shown.date.weekday())]}
    opened = EventForm(instance=event, initial=initial, series=series)
    data = _form_data(opened)
    # An occurrence of a repeating event changes alone
    if series is not None:
        data["scope"] = "this"
    data.update(_event_changes(args))
    form = EventForm(data, instance=event, series=series)
    if not form.is_valid():
        raise ToolError(_errors(form))
    result = save_event_edit(form, event, series, user, before)
    event.refresh_from_db()
    updated = {"updated": _event_info(event, user)}
    note = _sync_note(result)
    if note:
        updated["note"] = note
    return updated


# --- the catalogue -----------------------------------------------------------

DATE = {"type": "string", "format": "date", "description": "YYYY-MM-DD"}
TIME = {"type": "string", "description": "24-hour HH:MM"}
TASK_ID = {"type": "integer", "description": "The task's id"}
FOLDER_ID = {
    "type": ["integer", "null"],
    "description": "A task folder's id (list_task_folders); null for the Inbox",
}
PRIORITY = {"type": "string", "enum": PRIORITIES}

READ = {"readOnlyHint": True, "openWorldHint": False}
ADD = {
    "readOnlyHint": False,
    "destructiveHint": False,
    "idempotentHint": False,
    "openWorldHint": False,
}
CHANGE = {
    "readOnlyHint": False,
    "destructiveHint": True,
    "idempotentHint": True,
    "openWorldHint": False,
}
MARK = {
    "readOnlyHint": False,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": False,
}


def _schema(properties, required=()):
    return {
        "type": "object",
        "properties": properties,
        "required": list(required),
        "additionalProperties": False,
    }


TOOLS = [
    {
        "name": "list_task_folders",
        "title": "List task folders",
        "description": "The user's task folders, with their ids.",
        "inputSchema": _schema({}),
        "annotations": READ,
        "run": list_task_folders,
    },
    {
        "name": "find_tasks",
        "title": "Find tasks",
        "description": (
            "Find the user's tasks. Open tasks by default; filter by folder, "
            "due dates or text in the title. Undated tasks come last."
        ),
        "inputSchema": _schema(
            {
                "status": {"type": "string", "enum": ["open", "done", "all"]},
                "folder_id": FOLDER_ID,
                "due_from": DATE | {"description": "Due on or after (YYYY-MM-DD)"},
                "due_to": DATE | {"description": "Due on or before (YYYY-MM-DD)"},
                "text": {"type": "string", "description": "Words in the title"},
                "include_archived": {"type": "boolean"},
                "limit": {"type": "integer", "minimum": 1, "maximum": LIST_LIMIT},
            }
        ),
        "annotations": READ,
        "run": find_tasks,
    },
    {
        "name": "create_task",
        "title": "Add a task",
        "description": "Add a task to the user's list.",
        "inputSchema": _schema(
            {
                "title": {"type": "string", "maxLength": 200},
                "folder_id": FOLDER_ID,
                "due_date": DATE,
                "due_time": TIME,
                "priority": PRIORITY,
            },
            required=["title"],
        ),
        "annotations": ADD,
        "run": create_task,
    },
    {
        "name": "update_task",
        "title": "Change a task",
        "description": (
            "Change a task's title, folder, due date, due time or priority. "
            "Only the fields given change; a null due_date takes the date off. "
            "On a repeating task the change carries to its later instances, "
            "as on the site."
        ),
        "inputSchema": _schema(
            {
                "task_id": TASK_ID,
                "title": {"type": "string", "maxLength": 200},
                "folder_id": FOLDER_ID,
                "due_date": DATE | {"type": ["string", "null"]},
                "due_time": TIME | {"type": ["string", "null"]},
                "priority": PRIORITY,
            },
            required=["task_id"],
        ),
        "annotations": CHANGE,
        "run": update_task,
    },
    {
        "name": "complete_task",
        "title": "Complete a task",
        "description": (
            "Mark a task done. A repeating task's next instance comes on, "
            "and is returned as next."
        ),
        "inputSchema": _schema({"task_id": TASK_ID}, required=["task_id"]),
        "annotations": MARK,
        "run": complete_task,
    },
    {
        "name": "reopen_task",
        "title": "Reopen a task",
        "description": "Mark a done task as not done.",
        "inputSchema": _schema({"task_id": TASK_ID}, required=["task_id"]),
        "annotations": MARK,
        "run": reopen_task,
    },
    {
        "name": "list_events",
        "title": "List calendar events",
        "description": (
            "The user's calendar events between two days, inclusive: two weeks "
            "from today by default, a year at most."
        ),
        "inputSchema": _schema(
            {
                "start": DATE,
                "end": DATE,
                "text": {"type": "string", "description": "Words in the title"},
            }
        ),
        "annotations": READ,
        "run": list_events,
    },
    {
        "name": "create_event",
        "title": "Add a calendar event",
        "description": (
            "Add an event to the user's calendar. Without a start_time it is "
            "all day; with a start_time and no end_time it runs an hour. "
            "end_date is for an event over several days. It is copied to "
            "Google Calendar when the user has it connected."
        ),
        "inputSchema": _schema(
            {
                "title": {"type": "string", "minLength": 4, "maxLength": 255},
                "date": DATE,
                "end_date": DATE,
                "start_time": TIME,
                "end_time": TIME,
                "location": {"type": "string", "maxLength": 150},
            },
            required=["title", "date"],
        ),
        "annotations": ADD,
        "run": create_event,
    },
    {
        "name": "update_event",
        "title": "Change a calendar event",
        "description": (
            "Change an event's title, days, times or location. Only the fields "
            "given change; a null start_time makes it all day. On a repeating "
            "event only this occurrence changes."
        ),
        "inputSchema": _schema(
            {
                "event_id": {"type": "integer", "description": "The event's id"},
                "title": {"type": "string", "minLength": 4, "maxLength": 255},
                "date": DATE,
                "end_date": DATE | {"type": ["string", "null"]},
                "start_time": TIME | {"type": ["string", "null"]},
                "end_time": TIME | {"type": ["string", "null"]},
                "location": {"type": ["string", "null"], "maxLength": 150},
            },
            required=["event_id"],
        ),
        "annotations": CHANGE,
        "run": update_event,
    },
]

BY_NAME = {tool["name"]: tool for tool in TOOLS}


def listing():
    """The tools as tools/list gives them."""
    return [
        {key: value for key, value in tool.items() if key != "run"} for tool in TOOLS
    ]
