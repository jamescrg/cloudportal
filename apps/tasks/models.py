from datetime import datetime
from types import SimpleNamespace

from django.conf import settings
from django.db import models

from accounts.models import CustomUser
from apps.common.models import ReminderMixin, TimestampMixin, zone_or_default
from apps.common.recurrence import FREQUENCY_CHOICES, MONTHLY_BY_CHOICES, Rule, describe
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

    A recurring task is a hidden template (is_recurring) holding the rule it
    repeats by (the repeat_ fields; see apps.common.recurrence) and what each
    instance is; its instances are ordinary tasks (parent_task), one open
    at a time, the next made on the rule's next day (apps.tasks.recurring).
    """

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

    # A recurring task's template: the rule it repeats by
    is_recurring = models.BooleanField(default=False)
    repeat_frequency = models.CharField(
        max_length=10, choices=FREQUENCY_CHOICES, blank=True
    )
    repeat_interval = models.PositiveIntegerField(default=1)
    repeat_weekdays = models.CharField(max_length=20, blank=True)
    repeat_monthly_by = models.CharField(
        max_length=10, choices=MONTHLY_BY_CHOICES, default="day"
    )
    repeat_start = models.DateField(blank=True, null=True)
    repeat_until = models.DateField(blank=True, null=True)
    repeat_count = models.PositiveIntegerField(blank=True, null=True)
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
    def rule(self):
        """How a recurring template repeats, as the shared Rule; None for
        any other task."""
        if not self.is_recurring or not self.repeat_frequency or not self.repeat_start:
            return None
        return Rule(
            frequency=self.repeat_frequency,
            start=self.repeat_start,
            interval=self.repeat_interval,
            weekdays=self.repeat_weekdays,
            monthly_by=self.repeat_monthly_by,
            until=self.repeat_until,
            count=self.repeat_count,
        )

    def set_rule(self, pattern, start):
        """Give a template a rule: a pattern (apps.common.recurrence's
        pattern_for) counted from a day."""
        self.repeat_frequency = pattern["frequency"]
        self.repeat_interval = pattern["interval"]
        self.repeat_weekdays = pattern["weekdays"]
        self.repeat_monthly_by = pattern["monthly_by"]
        self.repeat_until = pattern["until"]
        self.repeat_count = pattern["count"]
        self.repeat_start = start

    @property
    def repeat_summary(self):
        """How a recurring task repeats, in words, from its template
        ("Weekly on Monday and Thursday"); empty for a task that does not."""
        template = self if self.is_recurring else self.parent_task
        rule = template.rule if template else None
        return describe(rule) if rule else ""

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
                channel=reminder.channel,
                amount=reminder.amount,
                unit=reminder.unit,
                time=reminder.time,
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
