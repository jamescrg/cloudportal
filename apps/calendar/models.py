from datetime import datetime, time, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import models
from django.utils import timezone

from accounts.models import CustomUser
from apps.common.models import TimestampMixin


def zone_or_default(name):
    """The zone of that name, or the app's when the name is not one."""
    try:
        return ZoneInfo(name or settings.TIME_ZONE)
    except (ValueError, KeyError, OSError):
        return ZoneInfo(settings.TIME_ZONE)


def is_zone(name):
    try:
        ZoneInfo(name)
    except (ValueError, KeyError, OSError, TypeError):
        return False
    return bool(name)


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


class EventReminder(models.Model):
    """A notification for an event, emailed some time before it.

    Attributes:
        event (int): the event the notification is for
        amount (int): how many of the unit before the event
        unit (str): minutes, hours, days or weeks
        time (time): for an all-day event, the time of day the notification
            goes out; ignored for a timed event, which counts back from
            its start time
        sent_for (datetime): the moment the notification was last sent for.
            It is compared with the moment it is now due, so an event that
            moves is notified again, and one that does not is notified once.
    """

    UNIT_CHOICES = [
        ("minutes", "minutes"),
        ("hours", "hours"),
        ("days", "days"),
        ("weeks", "weeks"),
    ]
    ALL_DAY_UNITS = ("days", "weeks")
    DEFAULT_TIME = time(9, 0)

    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="reminders")
    amount = models.PositiveIntegerField(default=0)
    unit = models.CharField(max_length=10, choices=UNIT_CHOICES, default="minutes")
    time = models.TimeField(null=True, blank=True)
    sent_for = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.describe()} : {self.event_id}"

    @property
    def offset(self):
        return timedelta(**{self.unit: self.amount})

    @property
    def fire_at(self):
        """When the notification goes out, in the app's time zone.

        A timed event counts back from its start, a fixed moment. An all-day
        event counts back whole days from its date and goes out at the
        notification's time of day where the user is now.
        """
        if self.event.start_time:
            return self.event.start_at - self.offset
        day = datetime.combine(
            self.event.date,
            self.time or self.DEFAULT_TIME,
            tzinfo=zone_or_default(self.event.user.time_zone),
        )
        return day - self.offset

    def describe(self):
        """The notification in words: "30 minutes before", "1 day before
        at 9:00 AM", "At the start", "That day at 9:00 AM"."""
        at = ""
        if not self.event.start_time:
            at = " at " + (self.time or self.DEFAULT_TIME).strftime("%-I:%M %p")
        if self.amount == 0:
            return ("That day" + at) if at else "At the start"
        unit = self.unit if self.amount != 1 else self.unit[:-1]
        return f"{self.amount} {unit} before{at}"

    class Meta:
        db_table = "app_event_reminder"
        ordering = ["-unit", "-amount"]


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
