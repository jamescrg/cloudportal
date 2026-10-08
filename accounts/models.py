from django.contrib.auth.models import AbstractUser
from django.db import models

from accounts.managers import CustomUserManager


class CustomUser(AbstractUser):
    objects = CustomUserManager()

    ROLE_OPTIONS = (
        ("ADMIN", "Admin"),
        ("USER", "User"),
    )

    role = models.CharField(max_length=5, choices=ROLE_OPTIONS, default="USER")
    zip = models.IntegerField(null=True, blank=True)
    phone_number = models.CharField(max_length=20, blank=True, default="")
    sms_notifications = models.BooleanField(default=False)
    email_reminders = models.BooleanField(default=False)
    notification_email = models.EmailField(blank=True, default="")
    # How notifications reach the user: by email, or pushed to the ntfy app
    # (apps.common.notify). ntfy delivers to anyone subscribed to a topic on
    # a server, so the topic is long and random; a server that is not open
    # to all wants an access token.
    NOTIFY_CHOICES = (("email", "Email"), ("ntfy", "ntfy"))
    notify_by = models.CharField(max_length=10, choices=NOTIFY_CHOICES, default="email")
    ntfy_server = models.URLField(default="https://ntfy.sh")
    ntfy_topic = models.CharField(max_length=64, blank=True, default="")
    ntfy_token = models.CharField(max_length=128, blank=True, default="")
    google_credentials = models.TextField(null=True, blank=True)
    # Whether the calendar syncs with Google Calendar. Separate from linking
    # a Google account, which contacts and the home page also use.
    calendar_sync = models.BooleanField(default=False)
    # Where the user is now, as their browser reports it on each page load.
    # Times they type are read in this zone, and the list and notifications
    # are shown and sent in it.
    time_zone = models.CharField(max_length=64, default="America/New_York")
    # Forwarded invitations: the unguessable part of the address the user
    # forwards them to, and the addresses (besides their own) they forward
    # from. One address per line.
    calendar_inbound_token = models.CharField(
        max_length=32, blank=True, null=True, unique=True
    )
    calendar_forward_from = models.TextField(blank=True, default="")
    extension_token = models.CharField(
        max_length=64, blank=True, null=True, unique=True
    )
    theme = models.TextField(default="", blank=True)
    search_engine = models.TextField(default="google", blank=True)
    home_events = models.IntegerField(default=0)
    home_events_hidden = models.DateField(null=True, blank=True)
    home_tasks = models.IntegerField(default=0)
    home_tasks_hidden = models.DateField(null=True, blank=True)
    home_due_tasks = models.IntegerField(default=0)
    home_due_tasks_hidden = models.DateField(null=True, blank=True)
    home_search = models.IntegerField(default=0)
    home_weather = models.IntegerField(default=1)
    weather_lat = models.FloatField(null=True, blank=True)
    weather_lon = models.FloatField(null=True, blank=True)
    favorites_folder = models.IntegerField(default=0)
    contacts_folder = models.IntegerField(default=0)
    contacts_contact = models.IntegerField(default=0)
    notes_folder = models.IntegerField(default=0)
    notes_note = models.IntegerField(default=0)
    tasks_folder = models.IntegerField(default=0)
    tasks_folders = models.JSONField(default=list)
    tasks_active_folder = models.IntegerField(default=0)
    encryption_salt = models.CharField(max_length=44, blank=True, default="")
    # Two-step sign-in with an authenticator app (accounts.totp): the shared
    # secret, set once the user has confirmed a code from the app (empty
    # means it is off), and the last 30-second step whose code was taken,
    # so a code can't be used twice
    totp_secret = models.CharField(max_length=32, blank=True, default="")
    totp_last_step = models.BigIntegerField(null=True, blank=True)
    task_completion_mode = models.CharField(
        max_length=10,
        choices=[
            ("complete", "Mark complete"),
            ("archive", "Auto-archive"),
            ("delete", "Auto-delete"),
        ],
        default="complete",
    )


class LoginThrottle(models.Model):
    """Failed sign-ins for one username, so repeated guessing has to wait
    (accounts.throttle). Keyed on the name as typed, folded to lower case,
    whether or not an account has it, so the waits don't reveal which
    names are real."""

    username = models.CharField(max_length=150, unique=True)
    failures = models.PositiveIntegerField(default=0)
    last_failure = models.DateTimeField()
    locked_until = models.DateTimeField(null=True, blank=True)


class RecoveryCode(models.Model):
    """A one-time code that stands in for the authenticator app, for when
    the phone is lost. Only a hash is kept; the codes themselves are shown
    once, when they are made."""

    user = models.ForeignKey(
        CustomUser, on_delete=models.CASCADE, related_name="recovery_codes"
    )
    code_hash = models.CharField(max_length=64)
    used_at = models.DateTimeField(null=True, blank=True)
