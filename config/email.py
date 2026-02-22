"""Email utility for task reminders."""

import logging

from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)


def send_task_reminder_email(user, task, reminder_type):
    """Send a task reminder email.

    Args:
        user: CustomUser instance
        task: Task instance
        reminder_type: "due_today", "due_soon", or "overdue"

    Returns:
        dict with 'success' boolean and optional 'error'
    """
    recipient = user.notification_email or user.email
    if not recipient:
        return {"success": False, "error": "User has no email address"}

    subject_map = {
        "due_today": f"Task Due Today: {task.title}",
        "due_soon": f"Task Due Soon: {task.title}",
        "overdue": f"Overdue Task: {task.title}",
    }
    subject = subject_map.get(reminder_type, f"Task Reminder: {task.title}")

    body = _build_body(task, reminder_type)

    try:
        send_mail(
            subject, body, settings.SERVER_EMAIL, [recipient], fail_silently=False
        )
        logger.info(
            f"Reminder sent to {recipient} for task {task.id} ({reminder_type})"
        )
        return {"success": True}
    except Exception as e:
        logger.error(f"Failed to send reminder to {recipient} for task {task.id}: {e}")
        return {"success": False, "error": str(e)}


def send_past_due_digest_email(user, tasks):
    """Send a single digest email listing all overdue tasks.

    Args:
        user: CustomUser instance
        tasks: iterable of overdue Task instances

    Returns:
        dict with 'success' boolean and optional 'error'
    """
    recipient = user.notification_email or user.email
    if not recipient:
        return {"success": False, "error": "User has no email address"}

    tasks = list(tasks)
    lines = ["You have the following past due tasks:", ""]
    for task in tasks:
        parts = [f"- {task.title}"]
        if task.due_date:
            parts.append(f"(due {task.due_date.strftime('%B %-d, %Y')})")
        if task.folder:
            parts.append(f"[{task.folder.name}]")
        lines.append(" ".join(parts))
    lines.append("")
    lines.append(f"-- {settings.SITE_NAME}")
    body = "\n".join(lines)

    try:
        send_mail(
            "Past Due Tasks",
            body,
            settings.SERVER_EMAIL,
            [recipient],
            fail_silently=False,
        )
        logger.info(f"Past due digest sent to {recipient} ({len(tasks)} tasks)")
        return {"success": True}
    except Exception as e:
        logger.error(f"Failed to send past due digest to {recipient}: {e}")
        return {"success": False, "error": str(e)}


def _build_body(task, reminder_type):
    """Build plain text email body."""
    lines = []
    if reminder_type == "due_today":
        lines.append(f'Your task "{task.title}" is due today.')
    elif reminder_type == "due_soon":
        time_str = task.due_time.strftime("%-I:%M %p") if task.due_time else ""
        lines.append(f'Your task "{task.title}" is due soon at {time_str}.')
    elif reminder_type == "overdue":
        lines.append(f'Your task "{task.title}" is overdue.')

    lines.append("")
    if task.due_date:
        lines.append(f"Due date: {task.due_date.strftime('%B %-d, %Y')}")
    if task.due_time:
        lines.append(f"Due time: {task.due_time.strftime('%-I:%M %p')}")
    if task.folder:
        lines.append(f"Folder: {task.folder.name}")
    lines.append("")
    lines.append(f"-- {settings.SITE_NAME}")
    return "\n".join(lines)
