import json
from datetime import datetime, timedelta
from email.utils import parseaddr
from logging import getLogger

from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods, require_POST

import apps.calendar.invitations as invitations
import apps.calendar.sync as sync
from apps.calendar.forms import EventForm
from apps.calendar.models import Event

from .events import (
    PAGINATION_KEY,
    SESSION_KEY,
    TRIGGER_KEY,
    VIEW_MODE_KEY,
    default_end_time,
    feed_filter,
    get_table_data,
    saved_filter,
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
    """Save a valid form's event for the user and push it to Google."""
    event = form.save(commit=False)
    event.user = user

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
            return _event_change_response(_save_event(form, request.user))
    else:
        form = EventForm(initial=_initial_from_click(request))

    context = {
        "page": "calendar",
        "edit": False,
        "action": "/calendar/add",
        "sync_on": request.user.calendar_sync,
        "google_connected": bool(request.user.google_credentials),
        "form": form,
    }
    return render(request, "calendar/form.html", context)


@login_required
def events_edit(request, id):
    event = _event_for_user(id, request.user)

    if request.method == "POST":
        form = EventForm(request.POST, instance=event)
        if form.is_valid():
            return _event_change_response(_save_event(form, request.user))
    else:
        form = EventForm(instance=event)

    context = {
        "page": "calendar",
        "edit": True,
        "action": f"/calendar/{id}/edit",
        "event": event,
        "sync_on": request.user.calendar_sync,
        "google_connected": bool(request.user.google_credentials),
        "form": form,
    }
    return render(request, "calendar/form.html", context)


@login_required
@require_http_methods(["POST", "DELETE"])
def events_delete(request, id):
    event = _event_for_user(id, request.user)

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
    # last, so one that began before the range still shows in it.
    events = (
        feed_filter(request)
        .qs.filter(date__lte=end_date)
        .filter(Q(end_date__gte=start_date) | Q(end_date=None, date__gte=start_date))
    )

    # Convert to FullCalendar format
    calendar_events = []
    for event in events:
        fc_event = {
            "id": str(event.id),
            "title": event.description or "Untitled",
            "extendedProps": {
                "event_type": event.event_type or "",
                "location": event.location or "",
            },
        }

        # Handle timed vs all-day events. FullCalendar's end is exclusive, so
        # an all-day event over several days ends the day after its last.
        if event.start_time and event.end_time:
            fc_event["start"] = f"{event.date}T{event.start_time}"
            fc_event["end"] = f"{event.last_date}T{event.end_time}"
            fc_event["allDay"] = False
        elif event.start_time:
            fc_event["start"] = f"{event.date}T{event.start_time}"
            fc_event["allDay"] = False
        else:
            fc_event["start"] = str(event.date)
            if event.end_date:
                fc_event["end"] = str(event.end_date + timedelta(days=1))
            fc_event["allDay"] = True

        calendar_events.append(fc_event)

    return JsonResponse(calendar_events, safe=False)


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
            invitation = invitations.parse_invitation(text)
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
