"""What the mobile sync API keeps of its own: the deletions it tells the
apps about, and the changes (ops) it has applied for each user."""

from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.utils import timezone

from accounts.models import CustomUser


class Tombstone(models.Model):
    """A task or task folder that someone can no longer see: deleted, or
    (a task) moved out of a shared folder into one they are not in.

    Attributes:
        kind (str): "task" or "folder"
        object_id (int): the task's or folder's id
        users (list): who could see it before and can't now, worked out
            when it happened (the owner, and the owner and editors of the
            folder it was in), so a later change to the folder's sharing
            doesn't change who hears of it
        deleted_at (datetime): when

    Kept for apps.api.sync.RETENTION, then pruned (apps.api.tracking.prune).
    """

    TASK = "task"
    FOLDER = "folder"
    KIND_CHOICES = ((TASK, "Task"), (FOLDER, "Folder"))

    kind = models.CharField(max_length=10, choices=KIND_CHOICES)
    object_id = models.BigIntegerField()
    users = ArrayField(models.BigIntegerField(), default=list)
    deleted_at = models.DateTimeField(default=timezone.now, db_index=True)

    def __str__(self):
        return f"{self.kind} {self.object_id} at {self.deleted_at}"


class AppliedOp(models.Model):
    """A change an app sent (POST /api/v1/ops), recorded with its result
    when it was applied, so the same op sent again is answered from here
    and not applied twice, and a later op can name what it made
    ("op:<id>").

    Attributes:
        user: whose op it was; op ids are the user's own
        op_id (uuid): the id the app gave it
        type (str): the op's type ("task.create")
        result (dict): what was answered, less the op's id: {"ok": true,
            "task_id": 120} or {"ok": false, "error": "gone", "message": ...}
        created_at (datetime): when it was applied
    """

    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    op_id = models.UUIDField()
    type = models.CharField(max_length=40)
    result = models.JSONField(default=dict)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "op_id"], name="api_op_once")
        ]

    def __str__(self):
        return f"{self.type} {self.op_id}"
