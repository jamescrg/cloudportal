from datetime import datetime
from types import SimpleNamespace

from django.conf import settings
from django.db import models

from accounts.models import CustomUser
from apps.common.models import ReminderMixin, TimestampMixin, zone_or_default
from apps.folders.models import Folder


class Task(TimestampMixin, models.Model):
    """A user's task.

    Attributes:
        id (int): the unique identifier for the favorite
        user (int): the user who created and owns the task
        folder (int): the folder to which the task belongs
        title (str): the content of the task, the thing to be done
        status (int): whether the task has been completed
            0: not completed
            1: completed
    """

    RECURRENCE_CHOICES = [
        ("daily", "Daily"),
        ("weekly", "Weekly"),
        ("monthly", "Monthly"),
        ("yearly", "Yearly"),
    ]

    id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    folder = models.ForeignKey(Folder, on_delete=models.SET_NULL, blank=True, null=True)
    title = models.CharField(max_length=200, null=True)
    status = models.IntegerField(blank=True, null=True, default=0)
    # 1 is highest, 10 lowest; 5 is Normal (see apps.tasks.priority)
    priority = models.IntegerField(default=5)
    archived = models.BooleanField(default=False)
    completed_date = models.DateField(blank=True, null=True)
    due_date = models.DateField(blank=True, null=True)
    due_time = models.TimeField(blank=True, null=True)
    # The zone the due date and time are in, so together they name a moment
    time_zone = models.CharField(max_length=64, default=settings.TIME_ZONE)
    reminder_sent_date = models.DateField(blank=True, null=True)

    # Recurrence fields
    is_recurring = models.BooleanField(default=False)
    recurrence_type = models.CharField(
        max_length=20, blank=True, null=True, choices=RECURRENCE_CHOICES
    )
    recurrence_day = models.IntegerField(blank=True, null=True)
    recurrence_month = models.IntegerField(blank=True, null=True)
    parent_task = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="instances",
    )
    last_generated = models.DateField(blank=True, null=True)

    def __str__(self):
        return f"{self.title} : {self.id}"

    @property
    def due_at(self):
        """The moment a task with a due time is due; None without one."""
        if not self.due_date or not self.due_time:
            return None
        return datetime.combine(
            self.due_date, self.due_time, tzinfo=zone_or_default(self.time_zone)
        )

    def in_zone(self, time_zone):
        """The due date and time as seen from a zone."""
        if not self.due_at:
            return SimpleNamespace(due_date=self.due_date, due_time=self.due_time)
        local = self.due_at.astimezone(zone_or_default(time_zone))
        return SimpleNamespace(due_date=local.date(), due_time=local.time())

    @property
    def shown(self):
        """The due date and time where the task's owner is now."""
        if not self.due_at:
            return SimpleNamespace(due_date=self.due_date, due_time=self.due_time)
        return self.in_zone(self.user.time_zone)

    def copy_reminders_from(self, template):
        """Give this task the notifications its recurring template has."""
        for reminder in template.reminders.all():
            self.reminders.create(
                amount=reminder.amount, unit=reminder.unit, time=reminder.time
            )

    class Meta:
        db_table = "app_task"


class TaskReminder(ReminderMixin):
    """A notification for a task (see ReminderMixin). A task with a due
    time counts back from that moment; one with only a due date counts
    back in days or weeks to a time of day."""

    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="reminders")

    class Meta(ReminderMixin.Meta):
        db_table = "app_task_reminder"

    @property
    def target(self):
        return self.task

    @property
    def target_id(self):
        return self.task_id

    @property
    def target_user(self):
        return self.task.user

    @property
    def target_start_at(self):
        return self.task.due_at

    @property
    def target_date(self):
        return self.task.due_date
