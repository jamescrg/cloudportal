"""US federal holidays, overlaid on the calendar.

The grid can show the federal holidays beside the user's events, as it
shows their tasks and their Kosmos events: read-only all-day entries that
open nothing. The dates come from the holidays package, which knows the
observed day when a holiday falls on a weekend.
"""

import holidays as holidays_lib

COUNTRY = "US"


def feed(first, last):
    """The federal holidays between two days, as FullCalendar events."""
    years = range(first.year, last.year + 1)
    calendar = holidays_lib.country_holidays(COUNTRY, years=years, observed=True)
    return [
        {
            "id": f"holiday-{day.isoformat()}",
            "title": name,
            "start": day.isoformat(),
            "allDay": True,
            "className": "fc-event-holiday",
            "editable": False,
            "extendedProps": {"kind": "holiday"},
        }
        for day, name in sorted(calendar.items())
        if first <= day <= last
    ]
