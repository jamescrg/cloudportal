from django.db import models

from accounts.models import CustomUser
from apps.common.models import TimestampMixin
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
    priority = models.IntegerField(default=1)
    archived = models.BooleanField(default=False)
    completed_date = models.DateField(blank=True, null=True)
    due_date = models.DateField(blank=True, null=True)
    due_time = models.TimeField(blank=True, null=True)
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

    class Meta:
        db_table = "app_task"
