"""The year view is a FullCalendar multi-month view of the next twelve
months: it is offered in the toolbar, remembered like the other views, and
the month view's tall cells stay out of its mini months."""

import re
from pathlib import Path

from django.conf import settings

JS = Path(settings.BASE_DIR, "static/js/events-calendar.js").read_text()
CSS = Path(settings.BASE_DIR, "static/css/app-calendar.css").read_text()


def test_the_toolbar_offers_the_year_view():
    # The wide-screen toolbar; the phone's holds only Today
    toolbars = re.findall(r"right:\s*\"([^\"]+)\"", JS)
    views = [t for t in toolbars if "dayGridMonth" in t]

    assert views and views[0].split(",")[0] == "multiMonthRolling"


def test_the_year_view_is_remembered():
    valid = re.search(r"const valid = \[([^\]]+)\]", JS).group(1)

    assert "multiMonthRolling" in valid


def test_a_phone_opens_the_agenda():
    assert 'phone ? "listRolling" : this.savedView()' in JS
    assert '"/calendar/calendar/"' in JS


def test_the_month_views_cell_height_is_scoped_to_the_month_view():
    rule = re.search(r"([^\n{]+)\{[^}]*min-height:\s*6rem", CSS).group(1)

    assert ".fc-dayGridMonth-view" in rule


def test_the_year_view_runs_twelve_months_from_the_month_in_view():
    view = re.search(r"multiMonthRolling: \{(.*?)\n\s*\}", JS, re.S).group(1)

    assert 'type: "multiMonth"' in view
    assert "duration: { months: 12 }" in view
    assert 'dateAlignment: "month"' in view


def test_the_agenda_runs_a_month_from_the_day_in_view():
    view = re.search(r"listRolling: \{(.*?)buttonText", JS, re.S).group(1)

    assert 'type: "list"' in view
    assert "duration: { months: 1 }" in view
    assert 'dateAlignment: "day"' in view
