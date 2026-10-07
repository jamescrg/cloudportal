from django.contrib import admin

from apps.calendar.models import Event, EventSeries


class EventAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "date", "description")


admin.site.register(Event, EventAdmin)


class EventSeriesAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "description", "frequency", "start", "until")


admin.site.register(EventSeries, EventSeriesAdmin)
