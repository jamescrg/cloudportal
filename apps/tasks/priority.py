"""Priority as five named levels over the 1–10 scale the tasks keep.

The number is still what is stored, sorted and filtered on; the levels
are how it is shown and chosen, with an icon each, as the law app shows
importance.
"""

from datetime import date, timedelta

# (slug, name, icon, the number chosen for it, the highest number it covers)
LEVELS = [
    ("highest", "Highest", "icon-chevrons-up", 1, 1),
    ("high", "High", "icon-chevron-up", 3, 3),
    ("normal", "Normal", "icon-equal", 5, 6),
    ("low", "Low", "icon-chevron-down", 8, 8),
    ("lowest", "Lowest", "icon-chevrons-down", 10, 10),
]


def level_for(priority):
    """The level a priority number falls in, as a dict."""
    for slug, name, icon, value, top in LEVELS:
        if priority <= top:
            return {
                "slug": slug,
                "name": name,
                "icon": icon,
                "value": value,
                "top": top,
            }
    slug, name, icon, value, top = LEVELS[-1]
    return {"slug": slug, "name": name, "icon": icon, "value": value, "top": top}


def levels():
    return [level_for(top) for _, _, _, _, top in LEVELS]


DATE_FILTER_NAMES = {
    "all": "All Dates",
    "past_due": "Past Due",
    "today": "Today",
    "tomorrow": "Tomorrow",
    "next7": "Next 7 Days",
    "unscheduled": "Unscheduled",
}


def default_due_date(filter_data, today):
    """The due date a new task starts with, from the filter in force.

    A task added while looking at today's tasks is due today, and while
    looking at tomorrow's, tomorrow. More generally, a filter pinned to a
    single day (its from and to the same) gives that day, which is what the
    Tomorrow preset is. Any other view gives no date.
    """
    if filter_data.get("filter_label") == "today":
        return today
    start = filter_data.get("due_date_min") or ""
    end = filter_data.get("due_date_max") or ""
    if start and start == end:
        try:
            return date.fromisoformat(start)
        except ValueError:
            return None
    return None


def quick_date_filters(today):
    """The date dropdown's presets: filter_label -> the date values of the
    filter. A preset touches only the date dimension, so the rest of a
    saved filter (status, sort) is left as it is.

    Today and the next seven days are open-ended at the start, so past-due
    tasks stay in view.
    """
    day = "%Y-%m-%d"

    return {
        "all": {"due_date_min": "", "due_date_max": "", "has_due_date": ""},
        "unscheduled": {
            "due_date_min": "",
            "due_date_max": "",
            "has_due_date": "false",
        },
        "past_due": {
            "due_date_min": "",
            "due_date_max": (today - timedelta(days=1)).strftime(day),
            "has_due_date": "",
        },
        "today": {
            "due_date_min": "",
            "due_date_max": today.strftime(day),
            "has_due_date": "",
        },
        # A single forward day, with both ends set
        "tomorrow": {
            "due_date_min": (today + timedelta(days=1)).strftime(day),
            "due_date_max": (today + timedelta(days=1)).strftime(day),
            "has_due_date": "",
        },
        "next7": {
            "due_date_min": "",
            "due_date_max": (today + timedelta(days=6)).strftime(day),
            "has_due_date": "",
        },
    }
