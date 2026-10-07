import json
from datetime import datetime, timedelta
from email.utils import parseaddr
from logging import getLogger

from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse, QueryDict
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods, require_POST

import apps.calendar.invitations as invitations
import apps.calendar.recurrence as recurrence
import apps.calendar.sync as sync
from apps.calendar.forms import EventForm, ReminderForm
from apps.calendar.models import Event, EventReminder, is_zone

from .events import (
    PAGINATION_KEY,
    SESSION_KEY,
    SHOW_TASKS_KEY,
    TRIGGER_KEY,
    VIEW_MODE_KEY,
    default_end_time,
    feed_filter,
    get_table_data,
    saved_filter,
    show_tasks,
    toolbar_context,
    view_mode,
)

logger = getLogger(__name__)


def _event_change_response(sync_result):
    """A 204 + HX-Trigger response for an event change. A failed push to
    Google (the local save still went through — see google.best_effort) is
    logged; reconcile() retries it on the next sync."""
    if sync_result == "failed":
        logger.warning("Event saved, but the push to Google Calendar failed")
    return HttpResponse(status=204, headers={"HX-Trigger": TRIGGER_KEY})


def _event_for_user(id, user):
    """The user's event, or 404: another user's event is not theirs to see."""
    return get_object_or_404(Event, pk=id, user=user)


@login_required
def events_index(request):
    """The calendar page, in whichever view (grid or list) was last used."""
    context = toolbar_context(request)
    if view_mode(request) == "list":
        context = get_table_data(request)
    return render(request, "calendar/content.html", context)


@login_required
def events_list(request):
    """The calendar or list partial, by the view saved in the session."""
    if view_mode(request) == "calendar":
        return render(request, "calendar/calendar.html", toolbar_context(request))
    return render(request, "calendar/list.html", get_table_data(request))


@login_required
def events_calendar(request):
    """The calendar partial whatever view the session holds. A phone asks
    for it when the saved view is the list, since the grid's agenda view
    reads better there than the table."""
    return render(request, "calendar/calendar.html", toolbar_context(request))


@login_required
@require_POST
def events_show_tasks(request, state):
    """Show the user's open tasks on the grid beside the events, or hide
    them. The partial re-renders so the button reads the new state."""
    if state not in ("on", "off"):
        return HttpResponseBadRequest("Unknown state.")
    request.session[SHOW_TASKS_KEY] = state == "on"
    request.session.modified = True
    return HttpResponse(status=204, headers={"HX-Trigger": "eventsViewChanged"})


@login_required
@require_POST
def events_view_mode(request, mode):
    """Switch between the list and the calendar grid."""
    if mode not in ("list", "calendar"):
        return HttpResponseBadRequest("Unknown view.")
    request.session[VIEW_MODE_KEY] = mode
    request.session.modified = True
    return HttpResponse(status=204, headers={"HX-Trigger": "eventsViewChanged"})


def _filter_data_from_post(post):
    """A posted filter form as the session can keep it: one value per key,
    a list where a key was posted more than once, and no CSRF token."""
    return {
        key: values[0] if len(values) == 1 else values
        for key, values in post.lists()
        if key != "csrfmiddlewaretoken"
    }


@login_required
def events_filter(request):
    """Display or apply the event filter."""
    if request.method == "POST":
        request.session[SESSION_KEY] = _filter_data_from_post(request.POST)
        request.session[PAGINATION_KEY] = 1
        request.session.modified = True
        return HttpResponse(status=204, headers={"HX-Trigger": TRIGGER_KEY})

    filter_data = saved_filter(request)
    order = filter_data.get("order_by", "date")
    if isinstance(order, list):
        order = order[0] if order else "date"
    return render(
        request,
        "calendar/filter.html",
        {"filter_data": filter_data, "sort_value": order},
    )


@login_required
@require_POST
def events_filter_default(request):
    """Clear the event filter to its defaults."""
    request.session.pop(SESSION_KEY, None)
    request.session[PAGINATION_KEY] = 1
    return HttpResponse(status=204, headers={"HX-Trigger": TRIGGER_KEY})


@login_required
@require_POST
def events_filter_sort(request, order):
    """Sort the list by a column header click; a second click reverses it."""
    filter_data = saved_filter(request)

    current = filter_data.get("order_by", "")
    if isinstance(current, list):
        current = current[0] if current else ""

    if current == order:
        new_order = f"-{order}"
    else:
        new_order = order

    filter_data["order_by"] = new_order
    request.session[SESSION_KEY] = filter_data
    request.session[PAGINATION_KEY] = 1
    request.session.modified = True

    return HttpResponse(status=204, headers={"HX-Trigger": TRIGGER_KEY})


def _initial_from_click(request):
    """The date, and the start time when a time slot was clicked, that the
    calendar asks Add Event to open with. Anything unreadable falls back to
    today with no time."""
    initial = {"date": timezone.localdate()}

    # Only the date part is read, so a full date-time here still lands on
    # the day that was clicked.
    try:
        initial["date"] = datetime.strptime(
            request.GET.get("date", "")[:10], "%Y-%m-%d"
        ).date()
    except ValueError:
        pass

    try:
        initial["start_time"] = datetime.strptime(
            request.GET.get("start_time", "")[:5], "%H:%M"
        ).time()
    except ValueError:
        pass

    return initial


def _save_event(form, user):
    """Save a valid form's event for the user and push it to Google. The
    times were typed where the user is now, so that is the event's zone."""
    event = form.save(commit=False)
    event.user = user
    event.time_zone = user.time_zone

    # An event saved with a start and no end runs for an hour
    if event.start_time and not event.end_time:
        event.end_time = default_end_time(event.start_time)

    event.save()
    return sync.push_event(event)


@login_required
def events_add(request):
    if request.method == "POST":
        form = EventForm(request.POST)
        if form.is_valid():
            result = _save_event(form, request.user)
            rule = form.rule()
            if rule:
                recurrence.start_series(form.instance, rule)
            return _event_change_response(result)
    else:
        initial = _initial_from_click(request)
        # A weekly repeat starts out on the day's own weekday
        initial["weekdays"] = [str(initial["date"].weekday())]
        form = EventForm(initial=initial)

    context = {
        "page": "calendar",
        "edit": False,
        "action": "/calendar/add",
        "sync_on": request.user.calendar_sync,
        "google_connected": bool(request.user.google_credentials),
        "form": form,
    }
    return render(request, "calendar/form.html", context)


def _save_occurrence(form, event, series, user):
    """Save an edit to an occurrence of a repeating event.

    "This event" saves the one occurrence. "This and following events" with
    the same rule and the same day carries the edit to the later
    occurrences where they stand, so one moved by hand stays moved and each
    keeps its notifications and its Google event. Any other change to how
    it repeats, or to its day, ends the series the day before this
    occurrence (as it was) and starts a new one from it as saved, the way
    Google Calendar splits a series. Repeat set to none leaves this
    occurrence standing alone.
    """
    original_date = Event.objects.values_list("date", flat=True).get(pk=event.pk)
    rule = form.rule()
    same_rule = rule == recurrence.rule_of(series)
    if form.cleaned_data.get("scope") != "following" and same_rule:
        return _save_event(form, user)

    if same_rule and form.cleaned_data["date"] == original_date:
        result = _save_event(form, user)
        recurrence.update_following(series, event)
        return result

    result = _save_event(form, user)
    recurrence.end_before(series, original_date, keep=event)
    if rule:
        recurrence.start_series(event, rule)
    return result


@login_required
def events_edit(request, id):
    event = _event_for_user(id, request.user)
    series = event.series

    if request.method == "POST":
        form = EventForm(request.POST, instance=event, series=series)
        if form.is_valid():
            if series is None:
                result = _save_event(form, request.user)
                rule = form.rule()
                if rule:
                    recurrence.start_series(event, rule)
            else:
                result = _save_occurrence(form, event, series, request.user)
            return _event_change_response(result)
    else:
        # The form opens on the event as seen from where the user is now;
        # saving it re-anchors the same moment to that zone.
        shown = event.in_zone(request.user.time_zone)
        if series is not None:
            initial = vars(shown) | recurrence.form_initial(series)
        else:
            initial = vars(shown) | {"weekdays": [str(shown.date.weekday())]}
        form = EventForm(instance=event, initial=initial, series=series)

    context = {
        "page": "calendar",
        "edit": True,
        "action": f"/calendar/{id}/edit",
        "event": event,
        "sync_on": request.user.calendar_sync,
        "google_connected": bool(request.user.google_credentials),
        "form": form,
    } | _reminders_context(event)
    return render(request, "calendar/form.html", context)


def _reminders_context(event, reminder_form=None):
    """The Notifications section of the edit form: the event's reminders
    and the row that adds one (components/reminders.html)."""
    reminders = list(event.reminders.all())
    for reminder in reminders:
        reminder.delete_url = reverse(
            "calendar:reminder-delete", args=[event.id, reminder.id]
        )
    return {
        "event": event,
        "reminders": reminders,
        "reminder_form": reminder_form or ReminderForm(event=event),
        "reminder_add_url": reverse("calendar:reminder-add", args=[event.id]),
    }


@login_required
@require_POST
def reminder_add(request, id):
    """Add a notification to the event and re-render the section."""
    event = _event_for_user(id, request.user)
    form = ReminderForm(request.POST, event=event)
    if form.is_valid():
        reminder = form.save(commit=False)
        reminder.event = event
        reminder.save()
        # On a repeating event it goes on the later occurrences too
        recurrence.add_reminder(event, reminder)
        form = None
    return render(request, "components/reminders.html", _reminders_context(event, form))


@login_required
@require_http_methods(["POST", "DELETE"])
def reminder_delete(request, id, reminder_id):
    """Remove a notification from the event and re-render the section."""
    event = _event_for_user(id, request.user)
    reminder = EventReminder.objects.filter(event=event, pk=reminder_id).first()
    if reminder is not None:
        reminder.delete()
        # On a repeating event it leaves the later occurrences too
        recurrence.remove_reminder(event, reminder)
    return render(request, "components/reminders.html", _reminders_context(event))


@login_required
@require_http_methods(["POST", "DELETE"])
def events_delete(request, id):
    event = _event_for_user(id, request.user)

    # An occurrence deleted with "This and following events" ends its series
    # here; the occurrences go off Google through the deletion queue.
    # htmx sends a DELETE's fields in its body, which Django leaves unread
    if request.method == "DELETE":
        fields = QueryDict(request.body)
    else:
        fields = request.POST
    scope = request.GET.get("scope") or fields.get("scope")
    if event.series is not None and scope == "following":
        recurrence.end_before(event.series, event.date)
        return HttpResponse(status=204, headers={"HX-Trigger": TRIGGER_KEY})

    # Remove from Google (queues a retry on failure) before deleting locally.
    result = sync.delete_event_remote(event)
    if result == "failed":
        logger.warning("Event deleted, but couldn't remove it from Google Calendar")

    event.delete()

    return HttpResponse(status=204, headers={"HX-Trigger": TRIGGER_KEY})


def _feed_date(value):
    """The date in one of the feed's ISO date or date-time parameters."""
    return datetime.fromisoformat(value.replace("Z", "+00:00")).date()


@login_required
def events_api(request):
    """
    JSON API for FullCalendar event feed.
    Exception to HTMX HTML-only rule: calendar requires JSON.
    """
    start_param = request.GET.get("start")
    end_param = request.GET.get("end")

    # Parse FullCalendar's ISO date parameters
    try:
        if start_param:
            start_date = _feed_date(start_param)
        else:
            start_date = timezone.localdate() - timedelta(days=30)

        if end_param:
            end_date = _feed_date(end_param)
        else:
            end_date = timezone.localdate() + timedelta(days=60)
    except ValueError:
        return HttpResponseBadRequest("start and end must be ISO dates.")

    # The saved filter (less its period), over this user's events that touch
    # the range: an event over several days counts from its first day to its
    # last, so one that began before the range still shows in it. A day's
    # margin each side covers a timed event whose date reads differently in
    # the grid's zone than in its own.
    first, last = start_date - timedelta(days=1), end_date + timedelta(days=1)
    # Repeating events are made a year ahead; a look further out makes the
    # occurrences it needs
    recurrence.extend_for(request.user, last)
    events = (
        feed_filter(request)
        .qs.filter(date__lte=last)
        .filter(Q(end_date__gte=first) | Q(end_date=None, date__gte=first))
        .select_related("series")
    )

    # Convert to FullCalendar format
    calendar_events = []
    for event in events:
        fc_event = {
            "id": str(event.id),
            "title": event.description or "Untitled",
            "extendedProps": {
                "location": event.location or "",
            },
        }
        # A repeating event is marked, with its rule in words for a tooltip
        if event.series:
            fc_event["className"] = "fc-event-repeats"
            fc_event["extendedProps"]["repeats"] = event.series.summary

        # Handle timed vs all-day events. A timed event is sent as a moment
        # with its offset, and the grid draws it in the browser's own zone.
        # FullCalendar's end is exclusive, so an all-day event over several
        # days ends the day after its last.
        if event.start_time and event.end_time:
            fc_event["start"] = event.start_at.isoformat()
            fc_event["end"] = event.end_at.isoformat()
            fc_event["allDay"] = False
        elif event.start_time:
            fc_event["start"] = event.start_at.isoformat()
            fc_event["allDay"] = False
        else:
            fc_event["start"] = str(event.date)
            if event.end_date:
                fc_event["end"] = str(event.end_date + timedelta(days=1))
            fc_event["allDay"] = True

        calendar_events.append(fc_event)

    if show_tasks(request):
        calendar_events.extend(_task_feed(request.user, first, last))

    return JsonResponse(calendar_events, safe=False)


def _task_feed(user, first, last):
    """The user's open tasks due in the range, as FullCalendar events. A
    task is told from an event by its id prefix and its kind, and may be
    dragged to another day but not stretched."""
    from apps.tasks.models import Task

    tasks = Task.objects.filter(
        user=user,
        status=0,
        archived=False,
        is_recurring=False,
        due_date__gte=first,
        due_date__lte=last,
    )
    feed = []
    for task in tasks:
        fc_task = {
            "id": f"task-{task.id}",
            "title": task.title,
            "className": "fc-event-task",
            "durationEditable": False,
            "extendedProps": {"kind": "task", "task_id": task.id},
        }
        if task.due_time:
            fc_task["start"] = task.due_at.isoformat()
            fc_task["allDay"] = False
        else:
            fc_task["start"] = str(task.due_date)
            fc_task["allDay"] = True
        feed.append(fc_task)
    return feed


def _quick_update_changes(body):
    """The date and times a drag or resize asks for, or None when the
    request is not the JSON object of dates and times the calendar sends."""
    try:
        data = json.loads(body)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None

    changes = {}
    try:
        if "date" in data:
            changes["date"] = datetime.strptime(data["date"], "%Y-%m-%d").date()
        if "end_date" in data:
            changes["end_date"] = (
                datetime.strptime(data["end_date"], "%Y-%m-%d").date()
                if data["end_date"]
                else None
            )
        for field in ("start_time", "end_time"):
            if field in data:
                changes[field] = (
                    datetime.strptime(data[field], "%H:%M:%S").time()
                    if data[field]
                    else None
                )
        # The browser says which zone the dragged-to times are in
        if "time_zone" in data:
            if not is_zone(data["time_zone"]):
                return None
            changes["time_zone"] = data["time_zone"]
    except (ValueError, TypeError):
        return None
    return changes


@login_required
@require_POST
def events_quick_update(request, id):
    """
    Quick update for drag-drop operations.
    Only updates date/time fields.
    """
    event = _event_for_user(id, request.user)

    # Everything is read before anything is set, so a request that cannot
    # be read changes nothing.
    changes = _quick_update_changes(request.body)
    if changes is None:
        return HttpResponseBadRequest("Unreadable date or time.")

    for field, value in changes.items():
        setattr(event, field, value)

    # An end date that adds no days is none; one before the date is refused.
    if event.end_date and event.end_date <= event.date:
        if event.end_date < event.date:
            return HttpResponseBadRequest("End date must be after the date.")
        event.end_date = None

    event.save()

    return _event_change_response(sync.push_event(event))


@csrf_exempt
@require_POST
def calendar_inbound(request):
    """Mailgun's post of a message sent to a user's forwarding address.

    200 takes the message. 406 refuses it for good (Mailgun does not retry
    it): an address or sender that is not a user's, or a message with no
    invitation in it. A post without Mailgun's signature is refused outright.
    """
    if not invitations.signature_is_valid(request.POST):
        return HttpResponse("Bad signature", status=403)

    user = invitations.user_for_recipient(request.POST.get("recipient", ""))
    if user is None:
        logger.info("Forwarded invitation to an unknown address was dropped")
        return HttpResponse("Unknown address", status=406)

    sender = parseaddr(request.POST.get("from") or request.POST.get("sender", ""))[1]
    if sender.lower() not in invitations.allowed_senders(user):
        logger.info("Forwarded invitation from %s was dropped", sender)
        return HttpResponse("Sender not allowed", status=406)

    subject = request.POST.get("subject", "").strip() or "(no subject)"
    text = invitations.calendar_text(request)
    invitation = None
    if text is not None:
        try:
            invitation = invitations.parse_invitation(text, user.time_zone)
        except Exception:
            logger.exception("Forwarded invitation could not be read")
    if invitation is None:
        invitations.notify(
            user,
            "Calendar: invitation not posted",
            f'The message "{subject}" had no calendar invitation attached, '
            "so nothing was posted. Forward the invitation itself, with its "
            "attachment, rather than a copy of its text.",
        )
        return HttpResponse("No invitation", status=406)

    outcome, event = invitations.post_invitation(user, invitation)
    notes = {
        "created": ("Calendar: invitation posted", "Posted: {}."),
        "updated": ("Calendar: invitation updated", "Updated: {}."),
        "cancelled": ("Calendar: invitation cancelled", "Removed: {}."),
        "stale": (
            "Calendar: invitation not posted",
            "An older version of an invitation already posted arrived, so it "
            "was left as it is: {}.",
        ),
    }
    if outcome in notes:
        note_subject, note = notes[outcome]
        invitations.notify(user, note_subject, note.format(invitations.describe(event)))
    return HttpResponse("OK")
