from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils.crypto import salted_hmac

from accounts.managers import CustomUserManager

# The icons a user may choose to stand for them in the top bar (Lucide
# names), the plain person first, as the default
NAV_ICONS = [
    ("user", "Person"),
    ("chess-king", "King"),
    ("chess-queen", "Queen"),
    ("chess-rook", "Rook"),
    ("chess-bishop", "Bishop"),
    ("chess-knight", "Knight"),
    ("chess-pawn", "Pawn"),
    ("hamburger", "Hamburger"),
    ("toolbox", "Toolbox"),
    ("smile", "Smile"),
    ("laugh", "Laugh"),
    ("cat", "Cat"),
    ("dog", "Dog"),
    ("rabbit", "Rabbit"),
    ("squirrel", "Squirrel"),
    ("panda", "Panda"),
    ("turtle", "Turtle"),
    ("feather", "Feather"),
    ("bird", "Bird"),
    ("birdhouse", "Birdhouse"),
    ("rat", "Rat"),
    ("origami", "Origami"),
    ("rose", "Rose"),
    ("snail", "Snail"),
]


class CustomUser(AbstractUser):
    objects = CustomUserManager()

    def _get_session_auth_hash(self, secret=None):
        # Django's own hash, with the sign-out-everywhere count mixed in once
        # there is one; at nought it is exactly Django's, so adding it
        # signed no one out
        value = self.password
        if self.sessions_ended:
            value = f"{value}:{self.sessions_ended}"
        return salted_hmac(
            "django.contrib.auth.models.AbstractBaseUser.get_session_auth_hash",
            value,
            secret=secret,
            algorithm="sha256",
        ).hexdigest()

    class Meta(AbstractUser.Meta):
        constraints = [
            # Sign-in is by email (accounts.backends), so no two accounts
            # may share one, in any case
            models.UniqueConstraint(
                Lower("email"),
                name="accounts_customuser_email_unique",
                condition=~Q(email=""),
            ),
        ]

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
    # How notifications reach the user unless one says otherwise: by email,
    # pushed to the ntfy app, or as a card on the home page (the choices
    # are apps.common.models.CHANNEL_CHOICES; see apps.common.notify). It is
    # the default for each new notification on an event or task, and the
    # way the past-due digest goes. ntfy delivers to anyone subscribed to a
    # topic on a server, so the topic is long and random; a server that is
    # not open to all wants an access token.
    NOTIFY_CHOICES = (("email", "Email"), ("ntfy", "Push"), ("home", "Homepage"))
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
    search_engine = models.TextField(default="google", blank=True)
    home_events = models.IntegerField(default=0)
    home_events_hidden = models.DateField(null=True, blank=True)
    home_tasks = models.IntegerField(default=0)
    home_tasks_hidden = models.DateField(null=True, blank=True)
    home_due_tasks = models.IntegerField(default=0)
    home_due_tasks_hidden = models.DateField(null=True, blank=True)
    # The Quotes panel: shown on the home page (and hidden for a day by its
    # close button, like the other sections); picked at random (a shuffle
    # that comes round once before repeating) or in order; and the user's
    # place in their quotes, with the day it was last moved on
    home_quotes = models.IntegerField(default=1)
    home_quotes_hidden = models.DateField(null=True, blank=True)
    quotes_mode = models.CharField(max_length=10, default="random")
    quotes_cursor = models.IntegerField(default=0)
    quotes_cursor_date = models.DateField(null=True, blank=True)
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
    # Bumped by "Sign out everywhere" (Settings > Security). It goes into
    # the hash every session is checked against, so each session made
    # before the bump stops matching and is signed out
    sessions_ended = models.PositiveIntegerField(default=0)
    # The icon that stands for the user in the top bar, opening the account
    # menu (one of NAV_ICONS)
    nav_icon = models.CharField(max_length=40, choices=NAV_ICONS, default="user")
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
    """Failed sign-ins for one email address, so repeated guessing has to
    wait (accounts.throttle). Keyed on the address as typed, folded to
    lower case, whether or not an account has it, so the waits don't
    reveal which addresses are real."""

    login = models.CharField(max_length=254, unique=True)
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
