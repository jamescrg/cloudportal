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
    google_credentials = models.TextField(null=True, blank=True)
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
    favorites_folder = models.IntegerField(default=0)
    contacts_folder = models.IntegerField(default=0)
    contacts_contact = models.IntegerField(default=0)
    notes_folder = models.IntegerField(default=0)
    notes_note = models.IntegerField(default=0)
    tasks_folder = models.IntegerField(default=0)
    tasks_folders = models.JSONField(default=list)
    tasks_active_folder = models.IntegerField(default=0)
    encryption_salt = models.CharField(max_length=44, blank=True, default="")
    task_completion_mode = models.CharField(
        max_length=10,
        choices=[
            ("complete", "Mark complete"),
            ("archive", "Auto-archive"),
            ("delete", "Auto-delete"),
        ],
        default="complete",
    )
