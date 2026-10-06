"""The year view is FullCalendar's own multiMonthYear: it is offered in the
toolbar, remembered like the other views, and the month view's tall cells
stay out of its mini months."""

import re
from pathlib import Path

from django.conf import settings

JS = Path(settings.BASE_DIR, "static/js/events-calendar.js").read_text()
CSS = Path(settings.BASE_DIR, "static/css/app-calendar.css").read_text()


def test_the_toolbar_offers_the_year_view():
    toolbar = re.search(r"right:\s*\"([^\"]+)\"", JS).group(1)

    assert toolbar.split(",")[0] == "multiMonthYear"


def test_the_year_view_is_remembered():
    valid = re.search(r"const valid = \[([^\]]+)\]", JS).group(1)

    assert "multiMonthYear" in valid


def test_the_month_views_cell_height_is_scoped_to_the_month_view():
    rule = re.search(r"([^\n{]+)\{[^}]*min-height:\s*6rem", CSS).group(1)

    assert ".fc-dayGridMonth-view" in rule
