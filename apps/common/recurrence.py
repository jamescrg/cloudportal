"""Repeat rules, shared by repeating events and recurring tasks.

A rule says how something repeats: its frequency (daily, weekly, monthly,
yearly), every how many of those (interval), on which weekdays (weekly),
by the day of the month or the weekday of the week (monthly), from which
day it counts (start), and when it ends (until a day, after a number of
times, or never). Each model keeps a rule in its own columns and hands it
over as a Rule (EventSeries.rule, Task.rule); everything here works on a
Rule, so events and tasks repeat by the same arithmetic and read the same
in words.

The form's Repeat choices map onto rules by pattern_for; the fields that
ask for them are apps.common.forms.RepeatFields, rendered by
templates/components/repeat-fields.html, with the labels that follow the
date set by the repeatFields Alpine component (static/js/alpine-components.js).
"""

from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta

from dateutil import rrule

WEEKDAYS = "0,1,2,3,4"  # Monday to Friday

FREQUENCIES = {
    "daily": rrule.DAILY,
    "weekly": rrule.WEEKLY,
    "monthly": rrule.MONTHLY,
    "yearly": rrule.YEARLY,
}

FREQUENCY_CHOICES = [
    ("daily", "Daily"),
    ("weekly", "Weekly"),
    ("monthly", "Monthly"),
    ("yearly", "Yearly"),
]
MONTHLY_BY_CHOICES = [("day", "Day of the month"), ("weekday", "Weekday")]

# The form's Repeat choices, each a frequency and what it fixes. The page
# relabels them from the date ("Monthly on the second Tuesday").
REPEAT_CHOICES = [
    ("", "Does not repeat"),
    ("daily", "Daily"),
    ("weekdays", "Every weekday (Monday to Friday)"),
    ("weekly", "Weekly"),
    ("monthly", "Monthly on the same day"),
    ("monthly_weekday", "Monthly on the same weekday"),
    ("yearly", "Yearly"),
]


@dataclass(frozen=True)
class Rule:
    frequency: str
    start: date
    interval: int = 1
    weekdays: str = ""
    monthly_by: str = "day"
    until: date | None = None
    count: int | None = None

    @property
    def weekday_list(self):
        return [int(day) for day in self.weekdays.split(",") if day.strip()]

    def pattern(self):
        """The rule less the day it counts from: what a form asks for, and
        what tells a changed rule from the same one started elsewhere."""
        fields = asdict(self)
        del fields["start"]
        return fields


def nth_weekday(day):
    """Which of its weekday in the month a day is: 1 for the first Tuesday.
    A fifth is the month's last, and repeats as the last (-1), since most
    months have no fifth."""
    nth = (day.day - 1) // 7 + 1
    return -1 if nth == 5 else nth


def pattern_for(repeat, interval, weekdays, start, until=None, count=None):
    """The pattern (a Rule's fields but its start) from the form's choices,
    or None for something that does not repeat. A weekly pattern with no
    days chosen falls on the start's weekday."""
    if not repeat:
        return None
    pattern = {
        "frequency": repeat,
        "interval": interval or 1,
        "weekdays": "",
        "monthly_by": "day",
        "until": until,
        "count": count,
    }
    if repeat == "weekdays":
        pattern.update(frequency="weekly", interval=1, weekdays=WEEKDAYS)
    elif repeat == "weekly":
        days = sorted({int(d) for d in weekdays or []}) or [start.weekday()]
        pattern["weekdays"] = ",".join(str(d) for d in days)
    elif repeat == "monthly_weekday":
        pattern.update(frequency="monthly", monthly_by="weekday")
    return pattern


def repeat_of(rule):
    """The form's Repeat choice for a rule."""
    if rule.frequency == "weekly" and rule.interval == 1 and rule.weekdays == WEEKDAYS:
        return "weekdays"
    if rule.frequency == "monthly" and rule.monthly_by == "weekday":
        return "monthly_weekday"
    return rule.frequency


def form_initial(rule):
    """The Repeat fields' starting values for something that repeats by a
    rule."""
    if rule.until:
        ends = "on"
    elif rule.count:
        ends = "after"
    else:
        ends = "never"
    return {
        "repeat": repeat_of(rule),
        "interval": rule.interval,
        "weekdays": [str(d) for d in rule.weekday_list],
        "ends": ends,
        "until": rule.until,
        "count": rule.count,
    }


def _rrule(rule):
    options = {
        "freq": FREQUENCIES[rule.frequency],
        "interval": rule.interval,
        "dtstart": datetime.combine(rule.start, time.min),
    }
    if rule.frequency == "weekly":
        options["byweekday"] = rule.weekday_list or [rule.start.weekday()]
    elif rule.frequency == "monthly" and rule.monthly_by == "weekday":
        weekday = rrule.weekdays[rule.start.weekday()]
        options["byweekday"] = weekday(nth_weekday(rule.start))
    if rule.until:
        options["until"] = datetime.combine(rule.until, time.max)
    elif rule.count:
        options["count"] = rule.count
    return rrule.rrule(**options)


def days_between(rule, after, through):
    """The days the rule falls on after one day and up to another."""
    first = datetime.combine(after + timedelta(days=1), time.min)
    last = datetime.combine(through, time.max)
    return [moment.date() for moment in _rrule(rule).between(first, last, inc=True)]


def next_after(rule, day):
    """The first day the rule falls on after a day, or None once it has
    ended."""
    moment = _rrule(rule).after(datetime.combine(day, time.max))
    return moment.date() if moment else None


WEEKDAY_NAMES = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]
ORDINALS = {1: "first", 2: "second", 3: "third", 4: "fourth", -1: "last"}
UNITS = {"daily": "day", "weekly": "week", "monthly": "month", "yearly": "year"}
LEADS = {
    "daily": "Daily",
    "weekly": "Weekly",
    "monthly": "Monthly",
    "yearly": "Annually",
}


def _and(items):
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def describe(rule):
    """The rule in words: "Weekly on Tuesday and Thursday", "Every 2 months
    on the second Tuesday", "Annually on October 6, 10 times"."""
    start = rule.start
    if rule.interval == 1:
        lead = LEADS[rule.frequency]
    else:
        lead = f"Every {rule.interval} {UNITS[rule.frequency]}s"

    if rule.frequency == "weekly":
        if rule.interval == 1 and rule.weekdays == WEEKDAYS:
            text = "Every weekday"
        else:
            days = rule.weekday_list or [start.weekday()]
            text = f"{lead} on {_and([WEEKDAY_NAMES[d] for d in days])}"
    elif rule.frequency == "monthly":
        if rule.monthly_by == "weekday":
            nth = ORDINALS[nth_weekday(start)]
            text = f"{lead} on the {nth} {WEEKDAY_NAMES[start.weekday()]}"
        else:
            text = f"{lead} on day {start.day}"
    elif rule.frequency == "yearly":
        text = f"{lead} on {start.strftime('%B')} {start.day}"
    else:
        text = lead

    if rule.until:
        text += (
            f", until {rule.until.strftime('%b')} {rule.until.day}, {rule.until.year}"
        )
    elif rule.count:
        text += f", {rule.count} times"
    return text
