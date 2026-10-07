"""Task notifications: adding and removing them on a task, keeping a
recurring task's template in step, and sending the ones that are due."""

from collections import defaultdict
from datetime import date

from apps.common.reminders import send_due as _send_due
from apps.tasks.models import Task, TaskReminder
from config.email import send_past_due_digest_email, send_task_notification_email


def add_reminder(task, amount, unit, time):
    """Add a notification to the task. A recurring task's instance passes it
    on to its template, so every later instance has it too."""
    reminder = task.reminders.create(amount=amount, unit=unit, time=time)
    if task.parent_task_id:
        task.parent_task.reminders.get_or_create(amount=amount, unit=unit, time=time)
    return reminder


def remove_reminder(task, reminder_id):
    """Remove a notification from the task, and the same one from a
    recurring task's template."""
    reminder = task.reminders.filter(pk=reminder_id).first()
    if reminder is None:
        return
    if task.parent_task_id:
        task.parent_task.reminders.filter(
            amount=reminder.amount, unit=reminder.unit, time=reminder.time
        ).delete()
    reminder.delete()


def send_due(now=None):
    """Send every task notification that is due: for open, unarchived
    tasks that are not recurring templates. Returns (sent, errors)."""
    queryset = TaskReminder.objects.filter(
        task__status=0, task__archived=False, task__is_recurring=False
    ).select_related("task", "task__user", "task__folder")
    return _send_due(queryset, send_task_notification_email, now)


def send_past_due_digests(today=None):
    """Send each user who turned Email Reminders on one digest of their
    past-due tasks, once a day. Returns (digests, errors)."""
    today = today or date.today()
    overdue = (
        Task.objects.filter(
            status=0,
            archived=False,
            due_date__lt=today,
            is_recurring=False,
            user__email_reminders=True,
        )
        .exclude(user__notification_email="", user__email="")
        .exclude(reminder_sent_date=today)
        .select_related("user", "folder")
    )
    overdue_by_user = defaultdict(list)
    for task in overdue:
        overdue_by_user[task.user].append(task)

    digests = errors = 0
    for user, tasks in overdue_by_user.items():
        result = send_past_due_digest_email(user, tasks)
        if result["success"]:
            for task in tasks:
                task.reminder_sent_date = today
                task.save(update_fields=["reminder_sent_date"])
            digests += 1
        else:
            errors += 1
    return digests, errors


def send_all():
    """The scheduled job: the notifications that are due, then the
    past-due digests. Returns {"sent", "digests", "errors"}."""
    sent, errors = send_due()
    digests, digest_errors = send_past_due_digests()
    return {"sent": sent, "digests": digests, "errors": errors + digest_errors}
