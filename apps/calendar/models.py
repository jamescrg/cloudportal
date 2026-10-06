from datetime import datetime
from types import SimpleNamespace

from django.conf import settings
from django.db import models
from django.utils import timezone

from accounts.models import CustomUser
from apps.common.models import ReminderMixin, TimestampMixin, is_zone, zone_or_default

__all__ = [
    "Event",
    "EventReminder",
    "CalendarSyncState",
    "PendingGoogleDeletion",
    "is_zone",
    "zone_or_default",
]


class Event(TimestampMixin, models.Model):
    """An event on a user's calendar.

    Attributes:
        user (int): the user whose calendar the event is on
        date (date): the day of the event, or its first day
        end_date (date): the last day of an event that runs over several
            days; blank for an event on one day
        start_time (time): when a timed event starts; blank for an all-day event
        end_time (time): when a timed event ends
        time_zone (str): the zone the date and times are in. Together they
            name an exact moment, so an event made while travelling keeps
            its moment wherever it is looked at from
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
    time_zone = models.CharField(max_length=64, default=settings.TIME_ZONE)
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
    def zone(self):
        return zone_or_default(self.time_zone)

    @property
    def start_at(self):
        """The moment a timed event starts; None for an all-day event."""
        if not self.start_time:
            return None
        return datetime.combine(self.date, self.start_time, tzinfo=self.zone)

    @property
    def end_at(self):
        """The moment a timed event ends; None without an end time."""
        if not self.end_time:
            return None
        return datetime.combine(self.last_date, self.end_time, tzinfo=self.zone)

    def in_zone(self, time_zone):
        """The event's date, end date and times as seen from a zone: what
        the list shows and the form opens with. An all-day event reads the
        same everywhere."""
        if not self.start_time:
            return SimpleNamespace(
                date=self.date,
                end_date=self.end_date,
                start_time=None,
                end_time=None,
            )
        zone = zone_or_default(time_zone)
        start = self.start_at.astimezone(zone)
        end = self.end_at.astimezone(zone) if self.end_at else None
        end_date = end.date() if end and end.date() > start.date() else None
        return SimpleNamespace(
            date=start.date(),
            end_date=end_date,
            start_time=start.time(),
            end_time=end.time() if end else None,
        )

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


class EventReminder(ReminderMixin):
    """A notification for an event (see ReminderMixin)."""

    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="reminders")

    class Meta(ReminderMixin.Meta):
        db_table = "app_event_reminder"

    @property
    def target(self):
        return self.event

    @property
    def target_id(self):
        return self.event_id

    @property
    def target_user(self):
        return self.event.user

    @property
    def target_start_at(self):
        return self.event.start_at

    @property
    def target_date(self):
        return self.event.date


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
