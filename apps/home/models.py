"""The home page's notification cards (apps.common.notify, by the
"home" channel): a notice stays on the page until the user closes it."""

from django.db import models
from django.urls import reverse
from django.utils import timezone

from accounts.models import CustomUser
from apps.calendar.models import Event
from apps.tasks.models import Task


class HomeNoticeQuerySet(models.QuerySet):
    def open(self):
        return self.filter(dismissed_at__isnull=True)

    def open_for(self, user):
        return self.open().filter(user=user).select_related("task", "event")


class HomeNotice(models.Model):
    """A notification shown as a card on the home page: a task's, an
    event's, or the past-due digest. It stays until the user closes it, or
    the task or event is deleted. Fields:

        kind: "task", "event" or "digest"
        title: the heading; lines: the card's text, one line each
        task, event: what it is for, when it is for one thing
        dismissed_at: when the user closed it, or None while it shows
    """

    KIND_CHOICES = (("task", "Task"), ("event", "Event"), ("digest", "Digest"))

    user = models.ForeignKey(
        CustomUser, on_delete=models.CASCADE, related_name="home_notices"
    )
    kind = models.CharField(max_length=10, choices=KIND_CHOICES)
    title = models.CharField(max_length=255)
    lines = models.TextField(blank=True, default="")
    task = models.ForeignKey(
        Task, null=True, blank=True, on_delete=models.CASCADE, related_name="notices"
    )
    event = models.ForeignKey(
        Event, null=True, blank=True, on_delete=models.CASCADE, related_name="notices"
    )
    created_at = models.DateTimeField(default=timezone.now)
    dismissed_at = models.DateTimeField(null=True, blank=True)

    objects = HomeNoticeQuerySet.as_manager()

    class Meta:
        db_table = "app_home_notice"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user", "dismissed_at"])]

    def __str__(self):
        return f"{self.kind}: {self.title}"

    @property
    def link(self):
        """Where the card's title goes: the task's form, the calendar on
        the event's day where the user is, or the tasks page for the
        digest."""
        if self.task_id:
            return reverse("tasks-edit", args=[self.task_id])
        if self.event_id:
            day = self.event.in_zone(self.user.time_zone).date
            return reverse("calendar:index") + f"?date={day.isoformat()}"
        return reverse("tasks")

    @property
    def line_list(self):
        return [line for line in self.lines.splitlines() if line.strip()]

    def dismiss(self):
        if self.dismissed_at is None:
            self.dismissed_at = timezone.now()
            self.save(update_fields=["dismissed_at"])
