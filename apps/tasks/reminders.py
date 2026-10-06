"""Task notifications: adding and removing them on a task, keeping a
recurring task's template in step, and sending the ones that are due."""

from apps.common.reminders import send_due as _send_due
from apps.tasks.models import TaskReminder
from config.email import send_task_notification_email


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
