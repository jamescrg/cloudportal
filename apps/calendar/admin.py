from django.contrib import admin

from apps.calendar.models import Event


class EventAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "date", "description")


admin.site.register(Event, EventAdmin)
