"""Email utility for task and event reminders."""

import logging

from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)


def send_task_notification_email(user, task):
    """Send the notification for a task.

    Returns:
        dict with 'success' boolean and optional 'error'
    """
    recipient = user.notification_email or user.email
    if not recipient:
        return {"success": False, "error": "User has no email address"}

    shown = task.in_zone(user.time_zone)
    when = shown.due_date.strftime("%A, %B %-d")
    if shown.due_time:
        when += " at " + shown.due_time.strftime("%-I:%M %p")
    subject = f"{task.title} - due {when}"

    lines = [task.title, "", f"Due: {when}"]
    if task.folder:
        lines.append(f"Folder: {task.folder.name}")
    lines.append("")
    lines.append(f"-- {settings.SITE_NAME}")
    body = "\n".join(lines)

    try:
        send_mail(
            subject, body, settings.SERVER_EMAIL, [recipient], fail_silently=False
        )
        logger.info(f"Task notification sent to {recipient} for task {task.id}")
        return {"success": True}
    except Exception as e:
        logger.error(
            f"Failed to send task notification to {recipient} for task {task.id}: {e}"
        )
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


def send_event_reminder_email(user, event):
    """Send the notification for a calendar event.

    Returns:
        dict with 'success' boolean and optional 'error'
    """
    recipient = user.notification_email or user.email
    if not recipient:
        return {"success": False, "error": "User has no email address"}

    shown = event.in_zone(user.time_zone)
    when = shown.date.strftime("%A, %B %-d")
    if shown.start_time:
        when += " at " + shown.start_time.strftime("%-I:%M %p")
    subject = f"{event.description} - {when}"

    lines = [f"{event.description}", ""]
    lines.append(f"When: {when}")
    if shown.end_date:
        lines.append(f"Through: {shown.end_date.strftime('%A, %B %-d')}")
    if shown.start_time and shown.end_time:
        lines.append(f"Ends: {shown.end_time.strftime('%-I:%M %p')}")
    if event.location:
        lines.append(f"Location: {event.location}")
    lines.append("")
    lines.append(f"-- {settings.SITE_NAME}")
    body = "\n".join(lines)

    try:
        send_mail(
            subject, body, settings.SERVER_EMAIL, [recipient], fail_silently=False
        )
        logger.info(f"Event reminder sent to {recipient} for event {event.id}")
        return {"success": True}
    except Exception as e:
        logger.error(
            f"Failed to send event reminder to {recipient} for event {event.id}: {e}"
        )
        return {"success": False, "error": str(e)}
