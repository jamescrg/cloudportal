"""Repeating events: a rule on an EventSeries, and occurrences that are
ordinary events, made a year ahead and edited or deleted one at a time or
from one occurrence on."""

from datetime import date, time, timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

import apps.calendar.recurrence as recurrence
from apps.calendar.forms import EventForm
from apps.calendar.models import (
    Event,
    EventReminder,
    EventSeries,
    PendingGoogleDeletion,
)

pytestmark = pytest.mark.django_db

TODAY = date(2030, 1, 7)  # a Monday


def _series(user, **fields):
    defaults = {
        "user": user,
        "frequency": "daily",
        "start": TODAY,
        "generated_through": TODAY,
        "description": "Standup",
    }
    return EventSeries.objects.create(**(defaults | fields))


def _days(series, through):
    return recurrence.days_between(series, series.start - timedelta(days=1), through)


# --- the rule --------------------------------------------------------------


def test_daily_every_other_day(user):
    series = _series(user, interval=2)

    assert _days(series, TODAY + timedelta(days=6)) == [
        TODAY,
        TODAY + timedelta(days=2),
        TODAY + timedelta(days=4),
        TODAY + timedelta(days=6),
    ]


def test_weekly_on_chosen_days(user):
    series = _series(user, frequency="weekly", weekdays="1,3")  # Tue, Thu

    assert _days(series, date(2030, 1, 17)) == [
        date(2030, 1, 8),
        date(2030, 1, 10),
        date(2030, 1, 15),
        date(2030, 1, 17),
    ]


def test_a_weekly_rule_with_no_days_falls_on_the_start_s_weekday():
    rule = recurrence.rule_for("weekly", 1, [], TODAY)

    assert rule["weekdays"] == "0"


def test_every_weekday_is_monday_to_friday():
    rule = recurrence.rule_for("weekdays", 3, [], TODAY)

    assert rule["frequency"] == "weekly"
    assert rule["weekdays"] == "0,1,2,3,4"
    assert rule["interval"] == 1


def test_monthly_on_the_31st_skips_the_short_months(user):
    series = _series(user, frequency="monthly", start=date(2030, 1, 31))

    assert _days(series, date(2030, 5, 31)) == [
        date(2030, 1, 31),
        date(2030, 3, 31),
        date(2030, 5, 31),
    ]


def test_monthly_on_the_same_weekday(user):
    # The second Tuesday of January 2030
    series = _series(
        user, frequency="monthly", monthly_by="weekday", start=date(2030, 1, 8)
    )

    assert _days(series, date(2030, 3, 31)) == [
        date(2030, 1, 8),
        date(2030, 2, 12),
        date(2030, 3, 12),
    ]


def test_a_fifth_weekday_repeats_as_the_last(user):
    # The fifth (and last) Thursday of January 2030
    series = _series(
        user, frequency="monthly", monthly_by="weekday", start=date(2030, 1, 31)
    )

    assert _days(series, date(2030, 3, 31)) == [
        date(2030, 1, 31),
        date(2030, 2, 28),
        date(2030, 3, 28),
    ]


def test_yearly(user):
    series = _series(user, frequency="yearly")

    assert _days(series, date(2032, 12, 31)) == [
        TODAY,
        date(2031, 1, 7),
        date(2032, 1, 7),
    ]


def test_a_rule_ends_on_its_last_day(user):
    series = _series(user, until=TODAY + timedelta(days=2))

    assert _days(series, TODAY + timedelta(days=30)) == [
        TODAY,
        TODAY + timedelta(days=1),
        TODAY + timedelta(days=2),
    ]


def test_a_rule_ends_after_a_number_of_times(user):
    series = _series(user, count=3)

    assert len(_days(series, TODAY + timedelta(days=30))) == 3


# --- starting and topping up a series --------------------------------------


def _first(user, **fields):
    defaults = {
        "user": user,
        "date": TODAY,
        "start_time": time(9, 0),
        "end_time": time(9, 30),
        "description": "Standup",
        "location": "Zoom",
        "time_zone": "America/New_York",
    }
    return Event.objects.create(**(defaults | fields))


def test_a_series_makes_its_occurrences_a_year_ahead(user):
    first = _first(user)

    series = recurrence.start_series(
        first, recurrence.rule_for("daily", 1, [], first.date), today=TODAY
    )

    occurrences = Event.objects.filter(series=series).order_by("date")
    assert occurrences.count() == 366
    assert occurrences.first() == first
    assert occurrences.last().date == TODAY + recurrence.HORIZON
    assert series.generated_through == TODAY + recurrence.HORIZON
    later = occurrences[1]
    assert (later.start_time, later.end_time) == (time(9, 0), time(9, 30))
    assert (later.description, later.location) == ("Standup", "Zoom")
    assert later.time_zone == "America/New_York"
    # Made here, not yet on Google: the next sync pushes them
    assert later.google_synced_at is None


def test_an_occurrence_over_several_days_keeps_its_span(user):
    first = _first(
        user, start_time=None, end_time=None, end_date=TODAY + timedelta(days=2)
    )

    recurrence.start_series(
        first, recurrence.rule_for("weekly", 1, [], first.date), today=TODAY
    )

    second = Event.objects.get(series=first.series, date=TODAY + timedelta(days=7))
    assert second.end_date == TODAY + timedelta(days=9)


def test_occurrences_take_the_first_one_s_notifications(user):
    first = _first(user)
    EventReminder.objects.create(event=first, amount=10, unit="minutes")

    recurrence.start_series(
        first, recurrence.rule_for("weekly", 1, [], first.date), today=TODAY
    )

    second = Event.objects.get(series=first.series, date=TODAY + timedelta(days=7))
    assert [(r.amount, r.unit) for r in second.reminders.all()] == [(10, "minutes")]


def test_topping_up_makes_the_days_since(user):
    first = _first(user)
    series = recurrence.start_series(
        first, recurrence.rule_for("daily", 1, [], first.date), today=TODAY
    )

    made = recurrence.extend_all(today=TODAY + timedelta(days=5))

    assert made == 5
    assert Event.objects.filter(series=series).count() == 371


def test_a_series_that_has_ended_is_not_topped_up(user):
    first = _first(user)
    series = recurrence.start_series(
        first,
        recurrence.rule_for(
            "daily", 1, [], first.date, until=TODAY + timedelta(days=2)
        ),
        today=TODAY,
    )

    recurrence.extend_all(today=TODAY + timedelta(days=30))

    assert Event.objects.filter(series=series).count() == 3


# --- the form --------------------------------------------------------------


def _data(**changes):
    return {"date": str(TODAY), "description": "Standup"} | changes


def test_ending_on_a_day_needs_the_day():
    form = EventForm(_data(repeat="daily", ends="on"))

    assert not form.is_valid()
    assert "until" in form.errors


def test_the_last_day_cannot_be_before_the_date():
    form = EventForm(_data(repeat="daily", ends="on", until="2030-01-01"))

    assert not form.is_valid()
    assert "until" in form.errors


def test_ending_after_a_number_needs_the_number():
    form = EventForm(_data(repeat="daily", ends="after"))

    assert not form.is_valid()
    assert "count" in form.errors


def test_an_event_that_does_not_repeat_keeps_no_end():
    form = EventForm(_data(repeat="", ends="on", until="2030-02-01"))

    assert form.is_valid()
    assert form.rule() is None


def test_the_apply_to_choice_is_only_on_an_occurrence(user):
    assert "scope" not in EventForm().fields
    assert "scope" in EventForm(series=_series(user)).fields


# --- the views -------------------------------------------------------------


def _soon(days=1):
    return timezone.localdate() + timedelta(days=days)


def _weekly_series(client, user):
    start = _soon()
    client.post(
        reverse("calendar:add"),
        {
            "date": str(start),
            "description": "Standup",
            "repeat": "weekly",
            "interval": 1,
        },
    )
    return Event.objects.get(user=user, date=start).series


def test_adding_a_repeating_event_makes_its_occurrences(client, user):
    series = _weekly_series(client, user)

    assert series is not None
    assert series.occurrences.count() == 53
    assert series.weekdays == str(_soon().weekday())


def test_an_edit_to_this_event_leaves_the_rest(client, user):
    series = _weekly_series(client, user)
    second = series.occurrences.order_by("date")[1]

    client.post(
        reverse("calendar:edit", args=[second.id]),
        {
            "date": str(second.date),
            "description": "Standup moved",
            "repeat": "weekly",
            "interval": 1,
            "weekdays": series.weekdays,
            "scope": "this",
        },
    )

    descriptions = list(
        series.occurrences.order_by("date").values_list("description", flat=True)
    )
    assert descriptions[1] == "Standup moved"
    assert descriptions.count("Standup moved") == 1


def test_a_new_rule_from_an_occurrence_splits_the_series(client, user):
    series = _weekly_series(client, user)
    third = series.occurrences.order_by("date")[2]

    client.post(
        reverse("calendar:edit", args=[third.id]),
        {
            "date": str(third.date),
            "description": "Team sync",
            "repeat": "weekly",
            "interval": 2,
            "weekdays": series.weekdays,
            "scope": "following",
        },
    )

    series.refresh_from_db()
    third.refresh_from_db()
    assert series.until == third.date - timedelta(days=1)
    assert series.occurrences.count() == 2
    assert set(series.occurrences.values_list("description", flat=True)) == {"Standup"}
    assert third.series != series
    assert set(third.series.occurrences.values_list("description", flat=True)) == {
        "Team sync"
    }


def test_an_edit_to_the_first_occurrence_s_following_replaces_the_series(client, user):
    series = _weekly_series(client, user)
    first = series.occurrences.order_by("date")[0]

    client.post(
        reverse("calendar:edit", args=[first.id]),
        {
            "date": str(first.date),
            "description": "Team sync",
            "repeat": "daily",
            "interval": 1,
            "scope": "following",
        },
    )

    first.refresh_from_db()
    assert not EventSeries.objects.filter(pk=series.pk).exists()
    assert first.series.frequency == "daily"


def test_repeat_set_to_none_leaves_this_one_alone(client, user):
    series = _weekly_series(client, user)
    second = series.occurrences.order_by("date")[1]

    client.post(
        reverse("calendar:edit", args=[second.id]),
        {
            "date": str(second.date),
            "description": "Standup",
            "repeat": "",
            "scope": "this",
        },
    )

    second.refresh_from_db()
    assert second.series is None
    assert series.occurrences.count() == 1


def test_a_lone_event_set_to_repeat_starts_a_series(client, user):
    event = Event.objects.create(user=user, date=_soon(), description="Review")

    client.post(
        reverse("calendar:edit", args=[event.id]),
        {"date": str(event.date), "description": "Review", "repeat": "monthly"},
    )

    event.refresh_from_db()
    assert event.series.frequency == "monthly"
    assert event.series.occurrences.count() > 1


def test_the_edit_form_opens_on_the_series_rule(client, user):
    series = _weekly_series(client, user)
    occurrence = series.occurrences.first()

    response = client.get(reverse("calendar:edit", args=[occurrence.id]))

    form = response.context["form"]
    assert form["repeat"].value() == "weekly"
    assert "scope" in form.fields


def test_deleting_this_event_leaves_the_rest(client, user):
    series = _weekly_series(client, user)
    second = series.occurrences.order_by("date")[1]

    client.delete(reverse("calendar:delete", args=[second.id]) + "?scope=this")

    assert series.occurrences.count() == 52


def test_deleting_following_events_ends_the_series(client, user):
    series = _weekly_series(client, user)
    occurrences = list(series.occurrences.order_by("date"))
    Event.objects.filter(pk=occurrences[5].pk).update(google_id="g-5")

    client.delete(
        reverse("calendar:delete", args=[occurrences[3].id]) + "?scope=following"
    )

    series.refresh_from_db()
    assert series.occurrences.count() == 3
    assert series.until == occurrences[3].date - timedelta(days=1)
    # Off Google through the queue, not one call per occurrence
    assert PendingGoogleDeletion.objects.filter(google_id="g-5").exists()


def test_the_choice_may_come_in_the_body_of_the_delete(client, user):
    # As htmx sends it
    series = _weekly_series(client, user)
    occurrences = list(series.occurrences.order_by("date"))

    client.delete(
        reverse("calendar:delete", args=[occurrences[3].id]),
        "scope=following",
        content_type="application/x-www-form-urlencoded",
    )

    assert series.occurrences.count() == 3


def test_deleting_from_the_first_occurrence_deletes_the_series(client, user):
    series = _weekly_series(client, user)
    first = series.occurrences.order_by("date")[0]

    client.delete(reverse("calendar:delete", args=[first.id]) + "?scope=following")

    assert not EventSeries.objects.filter(pk=series.pk).exists()
    assert not Event.objects.filter(user=user).exists()


def test_a_notification_added_to_an_occurrence_goes_on_the_later_ones(client, user):
    series = _weekly_series(client, user)
    occurrences = list(series.occurrences.order_by("date"))

    client.post(
        reverse("calendar:reminder-add", args=[occurrences[2].id]),
        {"amount": 1, "unit": "days", "time": "09:00", "channel": "home"},
    )

    assert not occurrences[1].reminders.exists()
    assert occurrences[2].reminders.count() == 1
    assert occurrences[-1].reminders.get().channel == "home"
    series.refresh_from_db()
    assert series.reminders == [
        {"channel": "home", "amount": 1, "unit": "days", "time": "09:00:00"}
    ]


def test_a_notification_removed_from_an_occurrence_leaves_the_later_ones(client, user):
    series = _weekly_series(client, user)
    occurrences = list(series.occurrences.order_by("date"))
    client.post(
        reverse("calendar:reminder-add", args=[occurrences[0].id]),
        {"amount": 1, "unit": "days", "time": "09:00"},
    )
    reminder = occurrences[2].reminders.get()

    client.post(
        reverse("calendar:reminder-delete", args=[occurrences[2].id, reminder.id])
    )

    assert occurrences[0].reminders.count() == 1
    assert not occurrences[2].reminders.exists()
    assert not occurrences[-1].reminders.exists()
    series.refresh_from_db()
    assert series.reminders == []


# --- polish ----------------------------------------------------------------


def test_an_edit_to_following_with_the_same_rule_changes_them_in_place(client, user):
    series = _weekly_series(client, user)
    occurrences = list(series.occurrences.order_by("date"))
    # One moved by hand, and one already on Google
    moved = occurrences[4]
    Event.objects.filter(pk=moved.pk).update(date=moved.date + timedelta(days=1))
    Event.objects.filter(pk=occurrences[5].pk).update(google_id="g-5")
    pivot = occurrences[2]

    client.post(
        reverse("calendar:edit", args=[pivot.id]),
        {
            "date": str(pivot.date),
            "description": "Team sync",
            "start_time": "10:00",
            "repeat": "weekly",
            "interval": 1,
            "weekdays": series.weekdays,
            "scope": "following",
        },
    )

    series.refresh_from_db()
    assert series.until is None
    assert series.description == "Team sync"
    assert series.occurrences.count() == 53
    descriptions = list(
        series.occurrences.order_by("date").values_list("description", flat=True)
    )
    assert descriptions[:2] == ["Standup", "Standup"]
    assert set(descriptions[2:]) == {"Team sync"}
    moved_now = Event.objects.get(pk=moved.pk)
    assert moved_now.date == moved.date + timedelta(days=1)
    assert moved_now.start_time == time(10, 0)
    assert Event.objects.get(pk=occurrences[5].pk).google_id == "g-5"
    # Made later, the series' later occurrences read the new way too
    assert (
        recurrence.generate(series, series.generated_through + timedelta(days=14)) == 2
    )
    assert series.occurrences.order_by("-date").first().description == "Team sync"


def test_moving_the_day_of_following_events_splits_the_series(client, user):
    series = _weekly_series(client, user)
    third = series.occurrences.order_by("date")[2]

    client.post(
        reverse("calendar:edit", args=[third.id]),
        {
            "date": str(third.date + timedelta(days=1)),
            "description": "Standup",
            "repeat": "weekly",
            "interval": 1,
            "weekdays": series.weekdays,
            "scope": "following",
        },
    )

    series.refresh_from_db()
    assert series.until == third.date - timedelta(days=1)


@pytest.mark.parametrize(
    "fields, words",
    [
        ({"frequency": "daily"}, "Daily"),
        ({"frequency": "daily", "interval": 3}, "Every 3 days"),
        ({"frequency": "weekly", "weekdays": "1,3"}, "Weekly on Tuesday and Thursday"),
        ({"frequency": "weekly", "weekdays": "0,1,2,3,4"}, "Every weekday"),
        (
            {"frequency": "weekly", "interval": 2, "weekdays": ""},
            "Every 2 weeks on Monday",
        ),
        ({"frequency": "monthly"}, "Monthly on day 7"),
        (
            {"frequency": "monthly", "monthly_by": "weekday"},
            "Monthly on the first Monday",
        ),
        (
            {
                "frequency": "monthly",
                "monthly_by": "weekday",
                "start": date(2030, 1, 31),
            },
            "Monthly on the last Thursday",
        ),
        ({"frequency": "yearly"}, "Annually on January 7"),
        ({"frequency": "daily", "count": 10}, "Daily, 10 times"),
        ({"frequency": "daily", "until": date(2030, 3, 1)}, "Daily, until Mar 1, 2030"),
    ],
)
def test_a_rule_reads_in_words(user, fields, words):
    assert _series(user, **fields).summary == words


def test_looking_past_the_year_makes_the_occurrences_there(client, user):
    series = _weekly_series(client, user)
    far = timezone.localdate() + timedelta(days=500)

    rows = client.get(
        reverse("calendar:api"),
        {"start": str(far), "end": str(far + timedelta(days=30))},
    ).json()

    assert len(rows) >= 4
    series.refresh_from_db()
    assert series.generated_through >= far + timedelta(days=30)


def test_occurrences_are_never_made_past_ten_years(user):
    first = _first(user)
    series = recurrence.start_series(
        first, recurrence.rule_for("yearly", 1, [], first.date), today=TODAY
    )

    recurrence.extend_for(user, TODAY + timedelta(days=365 * 50), today=TODAY)

    series.refresh_from_db()
    assert series.generated_through == TODAY + recurrence.FURTHEST


def test_the_feed_marks_repeating_events(client, user):
    series = _weekly_series(client, user)
    Event.objects.create(user=user, date=_soon(), description="One-off")

    rows = client.get(
        reverse("calendar:api"), {"start": str(_soon()), "end": str(_soon(2))}
    ).json()

    marked = {row["title"]: row.get("className") for row in rows}
    assert marked == {"Standup": "fc-event-repeats", "One-off": None}
    repeating = next(row for row in rows if row["title"] == "Standup")
    assert repeating["extendedProps"]["repeats"] == series.summary


def test_the_edit_form_says_how_the_event_repeats(client, user):
    series = _weekly_series(client, user)

    page = client.get(
        reverse("calendar:edit", args=[series.occurrences.first().id])
    ).content.decode()

    assert series.summary in page
    assert "repeatFields(" in page
