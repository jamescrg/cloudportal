from django.urls import path

from . import views

app_name = "calendar"

urlpatterns = [
    path("", views.events_index, name="index"),
    path("list/", views.events_list, name="list"),
    path("calendar/", views.events_calendar, name="calendar"),
    path("api/", views.events_api, name="api"),
    path("add", views.events_add, name="add"),
    path("<int:id>/edit", views.events_edit, name="edit"),
    path("<int:id>/delete", views.events_delete, name="delete"),
    path("<int:id>/quick-update", views.events_quick_update, name="quick-update"),
    path("<int:id>/reminders/add", views.reminder_add, name="reminder-add"),
    path(
        "<int:id>/reminders/<int:reminder_id>/delete",
        views.reminder_delete,
        name="reminder-delete",
    ),
    path("<int:id>/guests/add", views.guest_add, name="guest-add"),
    path(
        "<int:id>/guests/<int:guest_id>/delete",
        views.guest_delete,
        name="guest-delete",
    ),
    path("view/<str:mode>", views.events_view_mode, name="view-mode"),
    path("tasks/<str:state>", views.events_show_tasks, name="show-tasks"),
    path("kosmos/<str:state>", views.events_show_kosmos, name="show-kosmos"),
    path("holidays/<str:state>", views.events_show_holidays, name="show-holidays"),
    path("filter/", views.events_filter, name="filter"),
    path("filter/default", views.events_filter_default, name="filter-default"),
    path("filter/sort/<str:order>", views.events_filter_sort, name="filter-sort"),
    path("inbound/", views.calendar_inbound, name="inbound"),
]
