"""Events from the user's Kosmos, overlaid on the calendar.

A user who runs Kosmos (the law practice app) gives Settings the address
of their Kosmos and their Kosmos token, the one its Claude Desktop page
issues. The calendar then asks that Kosmos for the events the user may
see there (its events/api/, apps.calendar.api in Kosmos) and shows them
beside its own, read-only, each opening in Kosmos. A Kosmos that cannot
be reached, or answers badly, contributes nothing and is logged.
"""

import logging
from datetime import datetime, time
from zoneinfo import ZoneInfo

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

TIMEOUT = 6


def connected(user):
    return bool(user.kosmos_url and user.kosmos_token)


def api_url(user):
    return user.kosmos_url.rstrip("/") + "/events/api/"


def fetch(user, first, last):
    """The events Kosmos has for the user between two days, as it sends
    them, with the zone they are in. Raises requests.RequestException or
    ValueError when Kosmos cannot be reached or does not answer in kind."""
    response = requests.get(
        api_url(user),
        params={"start": first.isoformat(), "end": last.isoformat()},
        headers={"X-Kosmos-Token": user.kosmos_token},
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict) or not isinstance(data.get("events"), list):
        raise ValueError("Kosmos did not answer with events")
    return data


def _moment(day, clock, zone):
    return datetime.combine(
        datetime.fromisoformat(day).date(), time.fromisoformat(clock), tzinfo=zone
    )


def feed(user, first, last):
    """The user's Kosmos events between two days as FullCalendar events:
    read-only, marked as Kosmos's, each with the link that opens it
    there. Nothing when Kosmos cannot be reached."""
    try:
        data = fetch(user, first, last)
    except (requests.RequestException, ValueError) as error:
        logger.warning("Kosmos events for %s could not be fetched: %s", user, error)
        return []
    try:
        zone = ZoneInfo(data.get("time_zone") or settings.TIME_ZONE)
    except (ValueError, KeyError, OSError):
        zone = ZoneInfo(settings.TIME_ZONE)
    events = []
    for row in data["events"]:
        try:
            events.append(_fc_event(row, zone))
        except (KeyError, ValueError, TypeError) as error:
            logger.warning("A Kosmos event could not be read: %s", error)
    return events


def _fc_event(row, zone):
    fc_event = {
        "id": f"kosmos-{row['id']}",
        "title": row.get("title") or "Untitled",
        "className": "fc-event-kosmos",
        "editable": False,
        "extendedProps": {
            "kind": "kosmos",
            "url": row.get("url") or "",
            "location": row.get("location") or "",
            "matter": row.get("matter") or "",
        },
    }
    if row.get("start_time"):
        fc_event["start"] = _moment(row["date"], row["start_time"], zone).isoformat()
        if row.get("end_time"):
            fc_event["end"] = _moment(row["date"], row["end_time"], zone).isoformat()
        fc_event["allDay"] = False
    else:
        fc_event["start"] = row["date"]
        fc_event["allDay"] = True
    return fc_event


def check(user):
    """Try the connection from Settings: how many events Kosmos has for
    the user this month, or the problem."""
    from datetime import date, timedelta

    today = date.today()
    try:
        data = fetch(user, today.replace(day=1), today + timedelta(days=31))
    except requests.RequestException as error:
        return {"ok": False, "error": f"Kosmos could not be reached: {error}"}
    except ValueError as error:
        return {"ok": False, "error": str(error)}
    return {"ok": True, "count": len(data["events"])}
