from django.contrib import admin

from .models import Task


class TaskAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "folder", "title", "status")
    list_filter = ("user", "status")


admin.site.register(Task, TaskAdmin)
