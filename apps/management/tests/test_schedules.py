"""The scheduled jobs: each names a function that exists, and setting them
up twice leaves one of each."""

from importlib import import_module

import pytest
from django_q.models import Schedule

from apps.management.schedules import install_schedules, schedule_specs

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("spec", schedule_specs(), ids=lambda spec: spec.name)
def test_each_job_names_a_function_that_exists(spec):
    module, name = spec.func.rsplit(".", 1)

    assert callable(getattr(import_module(module), name))


def test_setting_up_twice_leaves_one_of_each():
    install_schedules()
    results = install_schedules()

    assert not any(created for _, created in results)
    assert Schedule.objects.count() == len(schedule_specs())


def test_a_schedule_waits_for_its_next_slot():
    install_schedules()

    for schedule in Schedule.objects.all():
        assert schedule.schedule_type == Schedule.CRON
        assert schedule.next_run is not None


def test_the_recurring_events_job_tops_up_the_series():
    # Called the way the cluster calls it: with no arguments
    from apps.calendar.recurrence import extend_all

    assert extend_all() == 0
