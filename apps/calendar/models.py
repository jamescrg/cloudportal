from django.db import models
from django.utils import timezone

from accounts.models import CustomUser
from apps.common.models import TimestampMixin


class Event(TimestampMixin, models.Model):
    """An event on a user's calendar.

    Attributes:
        user (int): the user whose calendar the event is on
        date (date): the day of the event, or its first day
        end_date (date): the last day of an event that runs over several
            days; blank for an event on one day
        start_time (time): when a timed event starts; blank for an all-day event
        end_time (time): when a timed event ends
        description (str): what the event is
        event_type (str): how the event takes place (Zoom, Virtual, Phone,
            In-person)
        location (str): a meeting link or an address
        google_id (str): the event's id on Google Calendar, when it is there
        ical_uid (str): the identifier of the invitation the event came from,
            so an updated or cancelled invitation finds it again
        ical_sequence (int): the invitation's revision; an older one is stale
        google_synced_at (datetime): when the event was last pushed to Google
    """

    EVENT_TYPE_CHOICES = [
        ("Zoom", "Zoom"),
        ("Virtual", "Virtual"),
        ("Phone", "Phone"),
        ("In-person", "In-person"),
    ]

    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    date = models.DateField()
    # Set only for an event over several days: its last day, inclusive. An
    # event on one day keeps this blank, so "is it multi-day" is one check.
    end_date = models.DateField(blank=True, null=True)
    start_time = models.TimeField(blank=True, null=True)
    end_time = models.TimeField(blank=True, null=True)
    description = models.CharField(max_length=255, blank=True)
    event_type = models.CharField(
        max_length=50, choices=EVENT_TYPE_CHOICES, blank=True, null=True
    )
    # CharField (not TextField) on purpose: location is a short pointer — a
    # meeting link or an address — not a notes field. 150 still fits a Zoom
    # URL + passcode.
    location = models.CharField(max_length=150, blank=True, null=True)
    google_id = models.CharField(max_length=255, blank=True, null=True)
    # When this event was last successfully pushed to Google Calendar. NULL means
    # never pushed. The push is needed whenever this is NULL or older than
    # updated_at (a local edit since the last sync) — that single comparison
    # drives create, update, first-connect backfill, and retry-after-failure.
    # One more state: synced once and now without a google_id. That is an
    # event removed on Google and kept here (see detached_from_google); it is
    # never pushed again.
    google_synced_at = models.DateTimeField(null=True, blank=True)
    ical_uid = models.CharField(max_length=255, blank=True, null=True)
    ical_sequence = models.IntegerField(default=0)

    def __str__(self):
        return f"{self.description} : {self.id}"

    @property
    def last_date(self):
        """The day the event ends: its end date, or its only day."""
        return self.end_date or self.date

    @property
    def detached_from_google(self):
        """True for an event that was deleted on Google and kept here.

        The user took it off their Google calendar on purpose, so it must not
        go back as a new Google event. It is told apart from an event that was
        never pushed (no google_id, no google_synced_at) by still carrying
        the time of its last sync.
        """
        return not self.google_id and self.google_synced_at is not None

    class Meta:
        db_table = "app_event"
        indexes = [
            models.Index(fields=["user", "date"]),
            models.Index(fields=["user", "ical_uid"]),
        ]


class CalendarSyncState(models.Model):
    """The Google Calendar sync token a user's incremental sync continues from."""

    user = models.OneToOneField(
        CustomUser, on_delete=models.CASCADE, related_name="calendar_sync_state"
    )
    sync_token = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    last_sync_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Sync state for {self.user}"

    class Meta:
        db_table = "app_calendar_sync_state"


class PendingGoogleDeletion(models.Model):
    """A Google Calendar event that must be deleted remotely after a local
    delete whose push failed. The Event row is gone, so the marker can't live on
    it; reconcile() drains this and removes the record once Google confirms."""

    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    google_id = models.CharField(max_length=255)
    created_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"Pending deletion of {self.google_id}"

    class Meta:
        db_table = "app_calendar_pending_deletion"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "google_id"], name="unique_pending_deletion"
            ),
        ]
