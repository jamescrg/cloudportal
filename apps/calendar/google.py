"""Google Calendar for one user's events.

Credentials are the ones the user connected in Settings (stored on the user
record, as the home page and contacts use them), and the calendar is the
account's primary one.
"""

import functools
import json
from datetime import datetime, timedelta
from logging import getLogger
from zoneinfo import ZoneInfo

import google.oauth2.credentials
from dateutil import parser as date_parser
from django.conf import settings
from django.db.models import F
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logger = getLogger(__name__)

CALENDAR_ID = "primary"


def best_effort(default):
    """Calendar sync is a side effect — a failure (stale/invalid token, network,
    API error) must never block the local save. Catch and log, returning
    `default` so the caller proceeds. check_credentials() can return True for a
    token that's actually expired/revoked, so the call still has to be guarded."""

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except Exception:
                logger.exception("Google Calendar %s failed; continuing", fn.__name__)
                return default

        return wrapper

    return decorator


def check_credentials(user):
    """Whether the user's events sync with Google Calendar: sync is turned
    on in Settings and a Google account is connected."""
    return bool(user.calendar_sync and user.google_credentials)


def build_service(user):
    if not user.google_credentials:
        return False
    credentials = google.oauth2.credentials.Credentials.from_authorized_user_info(
        json.loads(user.google_credentials)
    )
    return build("calendar", "v3", credentials=credentials)


def event_title(event):
    """The title an event carries on Google."""
    return event.description or ""


def _event_body(event):
    """The event as Google's API takes it."""
    body = {"summary": event_title(event)}

    if event.start_time and event.end_time:
        # Timed event - use dateTime format
        start_datetime = datetime.combine(event.date, event.start_time)
        end_datetime = datetime.combine(event.last_date, event.end_time)
        body["start"] = {
            "dateTime": start_datetime.isoformat(),
            "timeZone": settings.TIME_ZONE,
        }
        body["end"] = {
            "dateTime": end_datetime.isoformat(),
            "timeZone": settings.TIME_ZONE,
        }
    else:
        # All-day event - use date format; Google's end date is exclusive
        body["start"] = {"date": str(event.date)}
        body["end"] = {"date": str(event.last_date + timedelta(days=1))}

    # Map the free-text location to Google's location field; fall back to
    # the meeting type so type-only events still show something there.
    if event.location:
        body["location"] = event.location
    elif event.event_type:
        body["location"] = event.event_type

    return body


@best_effort(default=None)
def add_event(event):
    service = build_service(event.user)
    if not service:
        return None

    google_event = (
        service.events()
        .insert(calendarId=CALENDAR_ID, body=_event_body(event))
        .execute()
    )
    return google_event.get("id") if google_event else None


@best_effort(default=False)
def edit_event(event):
    service = build_service(event.user)
    if not service:
        return False

    result = (
        service.events()
        .update(
            calendarId=CALENDAR_ID,
            eventId=event.google_id,
            body=_event_body(event),
        )
        .execute()
    )
    return bool(result)


@best_effort(default=False)
def delete_event_by_id(user, google_id):
    """Delete a Google event by id. Returns True on success or if it's already
    gone (404/410) — both mean "nothing left to delete." Real failures (auth,
    network) raise and are turned into False by best_effort so the caller can
    retry. Takes a bare id so reconcile can drain deletions without an Event."""
    service = build_service(user)
    if not service:
        return False

    try:
        service.events().delete(calendarId=CALENDAR_ID, eventId=google_id).execute()
    except HttpError as err:
        if err.resp.status in (404, 410):
            logger.info("Google event %s already gone (%s)", google_id, err.resp.status)
            return True
        raise

    return True


def delete_event(event):
    return delete_event_by_id(event.user, event.google_id)


def list_google_events(user, sync_token=None):
    """
    Fetch events from Google Calendar using incremental sync.

    Args:
        user: the user whose calendar is read
        sync_token: Optional sync token for incremental sync. If None, performs
            a full sync of events from now on.

    Returns:
        Tuple of (events_list, next_sync_token)
        - events_list: List of event dictionaries (including cancelled events)
        - next_sync_token: Token to use for next incremental sync

    Raises:
        Exception: If sync token is invalid (410 error), caller should retry
        without token
    """
    try:
        service = build_service(user)
        if not service:
            logger.error("Failed to build Google Calendar service")
            return ([], None)

        all_events = []
        page_token = None

        while True:
            params = {
                "calendarId": CALENDAR_ID,
                "singleEvents": True,
                "showDeleted": True,  # Include cancelled events for sync
            }

            if sync_token:
                # Incremental sync - use sync token
                params["syncToken"] = sync_token
            else:
                # Full sync - cannot use orderBy with syncToken
                params["timeMin"] = datetime.utcnow().isoformat() + "Z"
                params["maxResults"] = 2500

            if page_token:
                params["pageToken"] = page_token

            response = service.events().list(**params).execute()

            all_events.extend(response.get("items", []))

            page_token = response.get("nextPageToken")
            if not page_token:
                next_sync_token = response.get("nextSyncToken")
                break

        logger.info("Fetched %s events from Google Calendar", len(all_events))
        return (all_events, next_sync_token)

    except Exception as e:
        # Check for expired sync token (HTTP 410)
        if hasattr(e, "resp") and e.resp.status == 410:
            logger.warning("Sync token expired, full sync required")
            raise  # Re-raise so caller can retry without token
        logger.error("Error fetching events from Google Calendar: %s", e)
        return ([], None)


def sync_from_google(user):
    """
    Synchronize events from Google Calendar to local database.
    Uses incremental sync with sync tokens for efficiency.
    Conflict resolution: local changes take precedence.
    """
    # Import here to avoid circular dependency
    from apps.calendar.models import CalendarSyncState

    if not check_credentials(user):
        logger.error("No Google Calendar credentials for %s", user)
        return

    logger.info("Starting Google Calendar sync for %s", user)

    sync_state, created = CalendarSyncState.objects.get_or_create(user=user)
    sync_token = sync_state.sync_token if not created else None

    try:
        google_events, next_sync_token = list_google_events(user, sync_token)

        if google_events is None:
            logger.error("Failed to fetch events from Google Calendar")
            return

        logger.info("Processing %s events from Google Calendar", len(google_events))

        counts = {
            "created": 0,
            "updated": 0,
            "deleted": 0,
            "detached": 0,
            "skipped": 0,
        }

        for google_event in google_events:
            try:
                result = _process_google_event(user, google_event)
                counts[result] = counts.get(result, 0) + 1
            except Exception as e:
                logger.error("Error processing event %s: %s", google_event.get("id"), e)
                continue

        # Save new sync token
        if next_sync_token:
            sync_state.sync_token = next_sync_token
            sync_state.save()

        logger.info("Sync completed: %s", counts)

    except Exception as e:
        # Handle expired sync token
        if "410" in str(e) or "Sync token" in str(e):
            logger.warning("Sync token expired, performing full sync")
            sync_state.sync_token = None
            sync_state.save()
            # Retry without token
            sync_from_google(user)
        else:
            logger.error("Error during Google Calendar sync: %s", e)
            raise


def _process_google_event(user, google_event):
    """
    Process a single Google Calendar event for one user.
    Returns: 'created', 'updated', 'deleted', 'detached', or 'skipped'
    """
    from apps.calendar.models import Event, PendingGoogleDeletion

    google_id = google_event.get("id")
    status = google_event.get("status")

    # Handle deleted events
    if status == "cancelled":
        result = "skipped"
        for local_event in Event.objects.filter(user=user, google_id=google_id):
            if _has_unpushed_edits(local_event):
                _detach(local_event)
                logger.info("Kept event %s, deleted on Google", google_id)
                result = "detached"
            else:
                local_event.delete()
                logger.info("Deleted event %s", google_id)
                result = "deleted"
        return result

    # Parse Google event data
    try:
        event_data = _parse_google_event(google_event)
    except Exception as e:
        logger.error("Error parsing Google event %s: %s", google_id, e)
        return "skipped"

    event_data["description"] = _fit_description(
        (google_event.get("summary") or "").strip() or "Untitled"
    )

    try:
        local_event = Event.objects.get(user=user, google_id=google_id)

        # Local wins: if the local event has edits not yet pushed to Google
        # (never synced, or edited since the last successful push), don't let
        # Google overwrite it — the next reconcile() will push our version up.
        if _has_unpushed_edits(local_event):
            logger.info("Local event %s has unpushed edits; skipping", google_id)
            return "skipped"

        # Google is newer - update local
        for field, value in event_data.items():
            setattr(local_event, field, value)
        local_event.save()
        # Local now matches Google, so mark it synced — otherwise the save()
        # bumped updated_at and reconcile() would push it straight back.
        Event.objects.filter(pk=local_event.pk).update(google_synced_at=F("updated_at"))
        logger.info("Updated event %s", google_id)
        return "updated"

    except Event.DoesNotExist:
        # Don't re-create an event we deleted locally and queued for remote
        # deletion (reconcile() will remove it from Google).
        if PendingGoogleDeletion.objects.filter(
            user=user, google_id=google_id
        ).exists():
            logger.info("Skipping create of %s — pending deletion", google_id)
            return "skipped"

        new_event = Event.objects.create(user=user, google_id=google_id, **event_data)
        # A pulled event is in sync by definition; stamp synced_at == updated_at
        # so reconcile() doesn't treat it as a never-pushed local event.
        Event.objects.filter(pk=new_event.pk).update(google_synced_at=F("updated_at"))
        logger.info("Created event %s", google_id)
        return "created"


def _has_unpushed_edits(event):
    """True when the event was never pushed, or edited since its last push."""
    return event.google_synced_at is None or bool(
        event.updated_at and event.updated_at > event.google_synced_at
    )


def _detach(event):
    """Cut a kept event loose from the Google event that was deleted.

    Clearing google_id stops it matching that Google event again. Keeping a
    google_synced_at marks it as detached rather than never pushed (see
    Event.detached_from_google), so neither a later edit nor reconcile()
    sends it back to Google as a new event. .update() so the event's own
    updated_at is untouched.
    """
    from apps.calendar.models import Event

    Event.objects.filter(pk=event.pk).update(
        google_id=None, google_synced_at=F("updated_at")
    )


def _fit_description(text):
    """A title from Google, cut to what the description column holds."""
    from apps.calendar.events import fit_description

    return fit_description(text)


def _parse_google_event(google_event):
    """
    Parse Google Calendar event into local Event model fields.
    Extracts: date, start_time, end_time, event_type, location
    """
    from apps.calendar.models import Event

    event_data = {}

    start = google_event.get("start", {})
    end = google_event.get("end", {})

    if "date" in start:
        # All-day event
        event_data["date"] = date_parser.parse(start["date"]).date()
        event_data["start_time"] = None
        event_data["end_time"] = None
        # Google's end date is exclusive: the day after the last day
        event_data["end_date"] = None
        if "date" in end:
            last = date_parser.parse(end["date"]).date() - timedelta(days=1)
            if last > event_data["date"]:
                event_data["end_date"] = last
    elif "dateTime" in start:
        # Timed event. Google returns RFC3339 datetimes (typically UTC);
        # convert to the app's zone before storing wall-clock values —
        # storing the UTC clock verbatim shifts every synced event by the
        # UTC offset, compounding on each round trip.
        local_tz = ZoneInfo(settings.TIME_ZONE)
        start_dt = date_parser.parse(start["dateTime"])
        end_dt = date_parser.parse(end["dateTime"])
        if start_dt.tzinfo is not None:
            start_dt = start_dt.astimezone(local_tz)
        if end_dt.tzinfo is not None:
            end_dt = end_dt.astimezone(local_tz)
        event_data["date"] = start_dt.date()
        event_data["start_time"] = start_dt.time()
        event_data["end_time"] = end_dt.time()
        event_data["end_date"] = (
            end_dt.date() if end_dt.date() > start_dt.date() else None
        )

    # Parse location: a bare meeting-type value maps to event_type, anything
    # else is treated as a free-text location. Google's location is
    # unbounded; truncate to our column limit so a long value can't fail the
    # whole sync run. The location is always set, to nothing when Google
    # holds no free text, so one removed there is removed here. The meeting
    # type is left as it is: it is this app's own classification, and Google
    # only ever shows it in place of a missing location.
    location = google_event.get("location") or ""
    event_data["location"] = None
    if location in dict(Event.EVENT_TYPE_CHOICES):
        event_data["event_type"] = location
    elif location:
        max_length = Event._meta.get_field("location").max_length
        event_data["location"] = location[:max_length]

    return event_data
