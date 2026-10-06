from datetime import datetime, time, timedelta

from django.utils import timezone

from apps.calendar.filter import EventFilter
from apps.management.pagination import CustomPaginator

SESSION_KEY = "calendar_filter"
VIEW_MODE_KEY = "calendar_view_mode"
PAGINATION_KEY = "calendar_page"
TRIGGER_KEY = "eventsChanged"

DEFAULT_FILTER = {
    "period": "upcoming",
    "date_min": "",
    "date_max": "",
    "event_type": "",
    "order_by": "date",
}


def saved_filter(request):
    """The filter saved in the session, or the default when none is saved.

    Restore Defaults empties the saved filter. Every reader (the list, the
    calendar feed, the toolbar) comes through here, so an emptied filter
    means upcoming events in the list rather than every event there is.
    """
    data = request.session.get(SESSION_KEY)
    if not data:
        data = dict(DEFAULT_FILTER)
        request.session[SESSION_KEY] = data
        request.session.modified = True
    return data


def view_mode(request):
    return request.session.get(VIEW_MODE_KEY, "calendar")


def event_filter(request):
    """The saved filter applied to this user's events."""
    return EventFilter(saved_filter(request), user=request.user)


def feed_filter(request):
    """The saved filter as the calendar grid applies it: everything but the
    period. The grid shows whichever month it is on, past or future, so a
    period that hid half of it would read as missing events."""
    data = {
        key: value for key, value in saved_filter(request).items() if key != "period"
    }
    return EventFilter(data, user=request.user)


def filter_is_active(request):
    """Whether the saved filter differs from the default, for the toolbar's
    Filter button."""
    return saved_filter(request) != DEFAULT_FILTER


def fit_description(text):
    """Cut a title from outside (Google, an invitation) to what the
    description column holds. The cut falls on a word boundary where the
    text has one."""
    from apps.calendar.models import Event

    limit = Event._meta.get_field("description").max_length
    if len(text) <= limit:
        return text
    cut = text[:limit]
    if not text[limit].isspace():
        whole_words = cut.rpartition(" ")[0].rstrip()
        if whole_words:
            cut = whole_words
    return cut.rstrip()


def default_end_time(start_time):
    """The end time for an event saved with a start and no end: an hour
    later, kept on the same day. An event has one date, so an end past
    midnight would read as before the start. A start in the last minute of
    the day has no later time to end at and gets none."""
    start = datetime.combine(datetime.min, start_time)
    end = start + timedelta(hours=1)
    if end.date() == start.date():
        return end.time()
    last_minute = time(23, 59)
    return last_minute if start_time < last_minute else None


def current_order(filter):
    """The field the list is sorted by, without its direction."""
    order = filter.data.get("order_by", "date")
    if isinstance(order, list):
        order = order[0] if order else "date"
    return order.lstrip("-")


def toolbar_context(request):
    today = timezone.localdate()
    return {
        "page": "calendar",
        "view_mode": view_mode(request),
        "filter_active": filter_is_active(request),
        "today": today,
        "third_day": today + timedelta(days=3),
    }


def get_table_data(request):
    filter = event_filter(request)

    pagination = CustomPaginator(filter.qs, 20, request, PAGINATION_KEY)

    # The duration column: days for an event over several days, hours for a
    # timed event on one day, nothing for an all-day event.
    event_list = pagination.get_object_list()
    for event in event_list:
        event.shown = event.in_zone(request.user.time_zone)
        event.duration = None
        event.duration_days = None
        if event.shown.end_date:
            event.duration_days = (event.shown.end_date - event.shown.date).days + 1
        elif event.start_time and event.end_time:
            event.duration = (event.end_at - event.start_at).total_seconds() / 3600

    return toolbar_context(request) | {
        "pagination": pagination,
        "session_key": PAGINATION_KEY,
        "trigger_key": TRIGGER_KEY,
        "objects": event_list,
        "current_order": current_order(filter),
    }
