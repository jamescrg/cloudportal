from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .forms import CustomUserChangeForm, CustomUserCreationForm
from .models import CustomUser


class CustomUserAdmin(UserAdmin):
    add_form = CustomUserCreationForm
    form = CustomUserChangeForm
    model = CustomUser
    list_display = [
        "email",
        "username",
        "is_staff",
        "search_engine",
        "home_events",
        "home_events_hidden",
        "home_tasks",
        "home_tasks_hidden",
        "home_due_tasks",
        "home_due_tasks_hidden",
        "home_search",
        "favorites_folder",
        "contacts_folder",
        "contacts_contact",
        "notes_folder",
        "notes_note",
        "tasks_folder",
        "tasks_folders",
        "tasks_active_folder",
    ]
    fieldsets = UserAdmin.fieldsets + (
        (
            "Preferences",
            {
                "fields": (
                    "search_engine",
                    "zip",
                )
            },
        ),
        (
            "Home Page",
            {
                "fields": (
                    "home_events",
                    "home_events_hidden",
                    "home_tasks",
                    "home_tasks_hidden",
                    "home_due_tasks",
                    "home_due_tasks_hidden",
                    "home_search",
                )
            },
        ),
        (
            "Selected Items",
            {
                "fields": (
                    "favorites_folder",
                    "contacts_folder",
                    "contacts_contact",
                    "notes_folder",
                    "notes_note",
                    "tasks_folder",
                    "tasks_folders",
                    "tasks_active_folder",
                )
            },
        ),
    )


admin.site.register(CustomUser, CustomUserAdmin)
