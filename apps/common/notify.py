"""Notifications: an event or task reminder, or the past-due digest, sent
by one of three channels (apps.common.models.CHANNEL_CHOICES). Each
notification on an event or task names its own; the user's choice in
Settings (CustomUser.notify_by) is the default for new ones and the way
the digest goes.

By ntfy, a notification is pushed to the topic the user's ntfy app is
subscribed to (https://docs.ntfy.sh/publish/), arriving in seconds, with
buttons: a task's opens the tasks page or marks it done (through a signed
link that needs no login, apps.tasks.views.notify_done), an event's opens
the calendar. When ntfy cannot be reached the notification goes by email
instead, so one is not lost to an outage.

By email, it is the message config.email has always sent.

To the home page, it is a card (apps.home.notices) that stays there until
the user closes it.

A machine other than production (settings.NOT_PRODUCTION) pushes to each
topic with a suffix (settings.NTFY_TOPIC_SUFFIX), so it has a channel of
its own even with a copy of production's data, marks its titles
(NOTIFY_TITLE_PREFIX), and sends no notification email
(EMAIL_NOTIFICATIONS): a refreshed dev machine never doubles production's
notifications.

Each sender returns {"success": bool, "error": str}, as the email senders
do, for apps.common.reminders.send_due.
"""

import logging

import requests
from django.conf import settings
from django.core import signing
from django.urls import reverse

from apps.home import notices
from config import email

logger = logging.getLogger(__name__)

# How long a notification's Done button works
DONE_LINK_AGE = 60 * 60 * 24 * 30
DONE_SALT = "notify-task-done"


# --- ntfy -------------------------------------------------------------------


def ntfy_ready(user):
    """Whether the user has a topic to push to: one is made when they first
    choose Push in Settings."""
    return bool(user.ntfy_topic)


def topic(user):
    """The topic this machine pushes the user's notifications to: theirs,
    with this machine's suffix (-dev on the dev machine)."""
    return user.ntfy_topic + settings.NTFY_TOPIC_SUFFIX


def push(user, title, message, *, priority=3, tags=(), click=None, actions=()):
    """Publish one message to the user's ntfy topic. Returns
    {"success": bool, "error": str}."""
    body = {
        "topic": topic(user),
        "title": settings.NOTIFY_TITLE_PREFIX + title,
        "message": message,
        "priority": priority,
        "tags": list(tags),
    }
    if click:
        body["click"] = click
    if actions:
        body["actions"] = list(actions)
    headers = {}
    if user.ntfy_token:
        headers["Authorization"] = f"Bearer {user.ntfy_token}"
    try:
        response = requests.post(
            user.ntfy_server.rstrip("/"), json=body, headers=headers, timeout=10
        )
        response.raise_for_status()
    except requests.RequestException as error:
        logger.warning("ntfy push to %s failed: %s", user.ntfy_server, error)
        return {"success": False, "error": str(error)}
    return {"success": True}


def _site(path):
    return settings.SITE_URL + path if settings.SITE_URL else None


def _deliver(user, channel, *, pushed, emailed, posted):
    """Send one notification the way its channel says: to the home page it
    is posted as a card; by ntfy it is pushed, falling back to email if the
    push fails or ntfy is not set up; by email it is emailed. Where email
    notifications are off (the dev machine), nothing is emailed, and the
    notification counts as handled so it is not tried again every
    minute."""
    if channel == "home":
        posted()
        return {"success": True}
    if channel == "ntfy" and ntfy_ready(user):
        result = pushed()
        if result["success"]:
            return result
        if not settings.EMAIL_NOTIFICATIONS:
            return result
        logger.info("Falling back to email for %s", user)
    if not settings.EMAIL_NOTIFICATIONS:
        logger.info("Email notifications are off here; not emailing %s", user)
        return {"success": True, "skipped": "email off"}
    return emailed()


# --- what is sent -------------------------------------------------------------


def done_link(task):
    """A link that marks the task done, for a notification's button: signed,
    so it needs no login, and good for DONE_LINK_AGE."""
    token = signing.dumps({"task": task.pk, "user": task.user_id}, salt=DONE_SALT)
    return _site(reverse("tasks-notify-done", args=[token]))


def read_done_link(token):
    """The (task id, user id) a Done link was made for, or None for one that
    is forged or too old."""
    try:
        data = signing.loads(token, salt=DONE_SALT, max_age=DONE_LINK_AGE)
    except signing.BadSignature:
        return None
    return data.get("task"), data.get("user")


def _when(day, at):
    text = day.strftime("%A, %B %-d")
    if at:
        text += " at " + at.strftime("%-I:%M %p")
    return text


def _task_lines(user, task):
    shown = task.in_zone(user.time_zone)
    lines = [f"Due {_when(shown.due_date, shown.due_time)}"]
    if task.folder:
        lines.append(f"Folder: {task.folder.name}")
    return lines


def _event_lines(user, event):
    shown = event.in_zone(user.time_zone)
    lines = [_when(shown.date, shown.start_time)]
    if shown.start_time and shown.end_time:
        lines[0] += " – " + shown.end_time.strftime("%-I:%M %p")
    if shown.end_date:
        lines.append(f"Through {shown.end_date.strftime('%A, %B %-d')}")
    if event.location:
        lines.append(event.location)
    return lines


def task_reminder(user, task, channel=None):
    """A task's notification, by the channel named or the user's default."""
    lines = _task_lines(user, task)

    def pushed():
        tasks_page = _site(reverse("tasks"))
        actions = []
        if tasks_page:
            actions.append({"action": "view", "label": "Open", "url": tasks_page})
            actions.append(
                {
                    "action": "http",
                    "label": "Done",
                    "url": done_link(task),
                    "method": "POST",
                    "clear": True,
                }
            )
        return push(
            user,
            task.title,
            "\n".join(lines),
            priority=4,
            tags=["memo"],
            click=tasks_page,
            actions=actions,
        )

    return _deliver(
        user,
        channel or user.notify_by,
        pushed=pushed,
        emailed=lambda: email.send_task_notification_email(user, task),
        posted=lambda: notices.post_task(user, task, lines),
    )


def event_reminder(user, event, channel=None):
    """An event's notification, by the channel named or the user's default."""
    lines = _event_lines(user, event)

    def pushed():
        calendar_page = _site(reverse("calendar:index"))
        actions = (
            [{"action": "view", "label": "Open", "url": calendar_page}]
            if calendar_page
            else []
        )
        return push(
            user,
            event.description,
            "\n".join(lines),
            priority=4,
            tags=["date"],
            click=calendar_page,
            actions=actions,
        )

    return _deliver(
        user,
        channel or user.notify_by,
        pushed=pushed,
        emailed=lambda: email.send_event_reminder_email(user, event),
        posted=lambda: notices.post_event(user, event, lines),
    )


def _digest_lines(tasks, limit=None):
    lines = []
    for task in tasks[:limit]:
        line = f"• {task.title}"
        if task.due_date:
            line += f" (due {task.due_date.strftime('%b %-d')})"
        lines.append(line)
    if limit and len(tasks) > limit:
        lines.append(f"… and {len(tasks) - limit} more")
    return lines


def past_due_digest(user, tasks):
    """The daily digest of the user's past-due tasks, the way they chose in
    Settings."""
    tasks = list(tasks)
    title = f"{len(tasks)} past-due task{'s' if len(tasks) != 1 else ''}"

    def pushed():
        return push(
            user,
            title,
            "\n".join(_digest_lines(tasks, limit=20)),
            priority=3,
            tags=["warning"],
            click=_site(reverse("tasks")),
        )

    return _deliver(
        user,
        user.notify_by,
        pushed=pushed,
        emailed=lambda: email.send_past_due_digest_email(user, tasks),
        posted=lambda: notices.post_digest(user, title, _digest_lines(tasks)),
    )


def test_message(user):
    """A test push from Settings, so the user can see their phone is set up."""
    return push(
        user,
        f"{settings.SITE_NAME}: notifications are working",
        "Event and task notifications will arrive here.",
        priority=3,
        tags=["white_check_mark"],
        click=_site(reverse("settings-notifications")),
    )
