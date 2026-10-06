import pytest

from apps.calendar.forms import EventForm

pytestmark = pytest.mark.django_db


def test_form_valid(event_data):
    assert EventForm(event_data).is_valid()


def test_date_is_required(event_data):
    data = event_data | {"date": ""}
    form = EventForm(data)
    assert not form.is_valid()
    assert "date" in form.errors


# -----------------------------------------------------
# clean_description tests
# -----------------------------------------------------
def test_description_too_short(event_data):
    form = EventForm(event_data | {"description": "abc"})
    assert not form.is_valid()
    assert "4 or more" in form.errors["description"][0]


def test_description_too_long(event_data):
    form = EventForm(event_data | {"description": "a" * 256})
    assert not form.is_valid()
    assert form.errors["description"] == ["Description is limited to 255 characters."]


def test_description_may_fill_the_column(event_data):
    assert EventForm(event_data | {"description": "a" * 255}).is_valid()


# -----------------------------------------------------
# clean() cross-field validation tests
# -----------------------------------------------------
def test_end_time_must_be_after_start_time(event_data):
    form = EventForm(event_data | {"start_time": "14:00", "end_time": "13:00"})
    assert not form.is_valid()
    assert "after start time" in form.errors["end_time"][0]


def test_end_time_same_as_start_time(event_data):
    form = EventForm(event_data | {"start_time": "14:00", "end_time": "14:00"})
    assert not form.is_valid()
    assert "end_time" in form.errors


def test_valid_start_and_end_time(event_data):
    assert EventForm(
        event_data | {"start_time": "14:00", "end_time": "15:00"}
    ).is_valid()


def test_times_optional(event_data):
    assert EventForm(event_data | {"start_time": "", "end_time": ""}).is_valid()
