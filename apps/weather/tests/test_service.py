"""The weather service: fetching One Call (always mocked here, never the
real API), the place lookup, the helpers, and the report built from a
real response."""

import copy
import os
import time
from unittest.mock import MagicMock, patch

import pytest
import requests

from apps.weather import service
from apps.weather.service import (
    build_report,
    compass,
    fetch_one_call,
    icon_for,
    inches,
    moon_phase_name,
    next_hour,
    place_name,
    precipitation_kind,
    report_for,
    reverse_geocode,
    uv_level,
    wind,
)

GET = "apps.weather.service.requests.get"


def api_response(payload):
    response = MagicMock()
    response.json.return_value = payload
    return response


# fetch_one_call


def test_fetch_one_call_returns_the_response(onecall):
    with patch(GET, return_value=api_response(onecall)) as get:
        assert fetch_one_call(36.85, -76.29) == onecall
    assert get.call_args.args[0] == service.ONE_CALL_URL
    params = get.call_args.kwargs["params"]
    assert (params["lat"], params["lon"]) == (36.85, -76.29)
    assert params["units"] == "imperial"


def test_fetch_one_call_passes_a_timeout(onecall):
    with patch(GET, return_value=api_response(onecall)) as get:
        fetch_one_call(36.85, -76.29)
    assert get.call_args.kwargs["timeout"] == service.TIMEOUT
    assert service.TIMEOUT > 0


def test_fetch_one_call_caches(onecall):
    with patch(GET, return_value=api_response(onecall)) as get:
        first = fetch_one_call(36.85, -76.29)
        second = fetch_one_call(36.85, -76.29)
    assert get.call_count == 1
    assert first == second == onecall


def test_fetch_one_call_shares_the_cache_within_three_decimals(onecall):
    with patch(GET, return_value=api_response(onecall)) as get:
        fetch_one_call(36.8501, -76.2901)
        fetch_one_call(36.8504, -76.2899)
    assert get.call_count == 1


def test_fetch_one_call_doesnt_share_the_cache_beyond_three_decimals(onecall):
    with patch(GET, return_value=api_response(onecall)) as get:
        fetch_one_call(36.850, -76.290)
        fetch_one_call(36.851, -76.290)
    assert get.call_count == 2


def test_fetch_one_call_request_error():
    with patch(GET, side_effect=requests.ConnectionError) as get:
        assert fetch_one_call(36.85, -76.29) is None
        assert fetch_one_call(36.85, -76.29) is None
    # a failure isn't cached
    assert get.call_count == 2


def test_fetch_one_call_timeout():
    with patch(GET, side_effect=requests.Timeout):
        assert fetch_one_call(36.85, -76.29) is None


@pytest.mark.parametrize("error", [ValueError, requests.JSONDecodeError("x", "", 0)])
def test_fetch_one_call_bad_json(error):
    response = MagicMock()
    response.json.side_effect = error
    with patch(GET, return_value=response):
        assert fetch_one_call(36.85, -76.29) is None


@pytest.mark.parametrize(
    "body",
    [
        {
            "cod": 401,
            "message": "Invalid API key. Please see https://openweathermap.org/faq#error401",
        },
        {"current": {}},
        {"daily": []},
        [],
        None,
    ],
)
def test_fetch_one_call_error_body(body):
    with patch(GET, return_value=api_response(body)) as get:
        assert fetch_one_call(36.85, -76.29) is None
        assert fetch_one_call(36.85, -76.29) is None
    assert get.call_count == 2


# reverse_geocode and place_name


def test_reverse_geocode_us():
    places = [{"name": "Norfolk", "state": "Virginia", "country": "US"}]
    with patch(GET, return_value=api_response(places)) as get:
        assert reverse_geocode(36.85, -76.29) == "Norfolk, Virginia"
    assert get.call_args.args[0] == service.REVERSE_GEOCODE_URL
    assert "timeout" in get.call_args.kwargs


def test_reverse_geocode_outside_the_us():
    places = [{"name": "Paris", "state": "Ile-de-France", "country": "FR"}]
    with patch(GET, return_value=api_response(places)):
        assert reverse_geocode(48.85, 2.35) == "Paris, Ile-de-France"


def test_reverse_geocode_without_a_region():
    with patch(GET, return_value=api_response([{"name": "Nowhere"}])):
        assert reverse_geocode(0.5, 0.5) == "Nowhere"


@pytest.mark.parametrize("body", [[], {"cod": 401, "message": "Invalid API key"}, None])
def test_reverse_geocode_nothing_found(body):
    with patch(GET, return_value=api_response(body)):
        assert reverse_geocode(36.85, -76.29) == ""


def test_reverse_geocode_request_error():
    with patch(GET, side_effect=requests.ConnectionError):
        assert reverse_geocode(36.85, -76.29) == ""


def test_reverse_geocode_bad_json():
    response = MagicMock()
    response.json.side_effect = ValueError
    with patch(GET, return_value=response):
        assert reverse_geocode(36.85, -76.29) == ""


@pytest.mark.django_db
def test_place_name_looks_up_and_saves(user):
    user.weather_lat, user.weather_lon = 36.85, -76.29
    user.save()
    places = [{"name": "Norfolk", "state": "Virginia", "country": "US"}]
    with (
        patch(GET, return_value=api_response(places)),
        patch.object(user, "save", wraps=user.save) as save,
    ):
        assert place_name(user) == "Norfolk, Virginia"
    save.assert_called_once_with(update_fields=["weather_place"])
    user.refresh_from_db()
    assert user.weather_place == "Norfolk, Virginia"


@pytest.mark.django_db
def test_place_name_already_known(user):
    user.weather_lat, user.weather_lon = 36.85, -76.29
    user.weather_place = "Norfolk, Virginia"
    user.save()
    with patch(GET) as get, patch.object(user, "save") as save:
        assert place_name(user) == "Norfolk, Virginia"
    get.assert_not_called()
    save.assert_not_called()


@pytest.mark.django_db
def test_place_name_not_found_isnt_saved(user):
    user.weather_lat, user.weather_lon = 36.85, -76.29
    user.save()
    with (
        patch(GET, side_effect=requests.ConnectionError),
        patch.object(user, "save") as save,
    ):
        assert place_name(user) == ""
    save.assert_not_called()


# helpers


@pytest.mark.parametrize(
    "code, icon",
    [
        ("01d", "sun"),
        ("01n", "moon"),
        ("02d", "cloud-sun"),
        ("02n", "cloud-moon"),
        ("10d", "cloud-sun-rain"),
        ("10n", "cloud-moon-rain"),
        ("13n", "cloud-snow"),
        ("99d", "cloud"),
        ("99n", "cloud"),
    ],
)
def test_icon_for(code, icon):
    assert icon_for(code) == icon


@pytest.mark.parametrize(
    "degrees, point",
    [
        (0, "N"),
        (90, "E"),
        (180, "S"),
        (270, "W"),
        (350, "N"),
        (11, "N"),
        (12, "NNE"),
        (360, "N"),
        (None, ""),
    ],
)
def test_compass(degrees, point):
    assert compass(degrees) == point


@pytest.mark.parametrize(
    "uvi, level",
    [
        (0, "low"),
        (2.9, "low"),
        (3, "moderate"),
        (5.9, "moderate"),
        (6, "high"),
        (7.9, "high"),
        (8, "very high"),
        (10.9, "very high"),
        (11, "extreme"),
    ],
)
def test_uv_level(uvi, level):
    assert uv_level(uvi) == level


@pytest.mark.parametrize(
    "phase, name",
    [
        (0, "new moon"),
        (0.1, "waxing crescent"),
        (0.25, "first quarter"),
        (0.5, "full moon"),
        (0.75, "last quarter"),
        (0.99, "new moon"),
        (1, "new moon"),
    ],
)
def test_moon_phase_name(phase, name):
    assert moon_phase_name(phase) == name


@pytest.mark.parametrize(
    "mm, shown",
    [(0, ""), (None, ""), (0.5, "<0.1"), (25.4, "1.0"), (50.8, "2.0"), (2.54, "0.1")],
)
def test_inches(mm, shown):
    assert inches(mm) == shown


def minutes(*wet):
    """Sixty minutes of precipitation, wet in the given ranges."""
    return [
        {
            "dt": 1791653220 + 60 * i,
            "precipitation": 0.5 if any(i in r for r in wet) else 0,
        }
        for i in range(60)
    ]


def test_next_hour_without_minutely():
    assert next_hour(None, "rain") is None
    assert next_hour([], "rain") is None


def test_next_hour_dry():
    assert next_hour(minutes(), "rain") == {
        "text": "No rain expected in the next hour",
        "wet": False,
    }


def test_next_hour_wet_throughout():
    assert next_hour(minutes(range(60)), "rain") == {
        "text": "Rain for the next hour",
        "wet": True,
    }


def test_next_hour_wet_then_ends():
    assert next_hour(minutes(range(20)), "rain") == {
        "text": "Rain for the next 20 minutes",
        "wet": True,
    }


def test_next_hour_wet_ends_then_restarts():
    assert next_hour(minutes(range(20), range(40, 60)), "rain") == {
        "text": "Rain for the next 20 minutes, then more later in the hour",
        "wet": True,
    }


def test_next_hour_starts_later():
    assert next_hour(minutes(range(12, 60)), "rain") == {
        "text": "Rain starting in 12 minutes",
        "wet": True,
    }


def test_next_hour_kind_word():
    assert next_hour(minutes(), "snow")["text"] == "No snow expected in the next hour"
    assert next_hour(minutes(range(60)), "snow")["text"] == "Snow for the next hour"
    assert (
        next_hour(minutes(range(5, 60)), "precipitation")["text"]
        == "Precipitation starting in 5 minutes"
    )


def test_next_hour_missing_precipitation_is_dry():
    assert next_hour([{"dt": 1}] * 60, "rain")["wet"] is False


@pytest.mark.parametrize(
    "main, kind",
    [
        ("Snow", "snow"),
        ("Rain", "rain"),
        ("Drizzle", "rain"),
        ("Thunderstorm", "rain"),
        ("Clouds", "precipitation"),
        ("Clear", "precipitation"),
    ],
)
def test_precipitation_kind(main, kind):
    assert precipitation_kind([{"main": main}]) == kind


def test_precipitation_kind_without_weather():
    assert precipitation_kind([]) == "precipitation"


def test_wind_gust_shown_when_stronger():
    assert wind({"wind_speed": 10.4, "wind_deg": 90, "wind_gust": 10.6}) == {
        "wind_speed": 10,
        "wind_dir": "E",
        "wind_gust": 11,
        "wind_text": "10 mph E, gusts 11",
    }


def test_wind_gust_hidden_when_it_rounds_to_the_speed():
    assert (
        wind({"wind_speed": 10.2, "wind_deg": 90, "wind_gust": 10.4})["wind_gust"]
        is None
    )


def test_wind_gust_hidden_when_weaker():
    assert wind({"wind_speed": 12, "wind_deg": 90, "wind_gust": 8})["wind_gust"] is None


def test_wind_without_gust_or_direction():
    assert wind({"wind_speed": 3.6}) == {
        "wind_speed": 4,
        "wind_dir": "",
        "wind_gust": None,
        "wind_text": "4 mph",
    }


# build_report: times in the location's own zone


def test_times_are_the_locations_local_time(onecall):
    """The regression: the old helper read fromtimestamp's output (in the
    process's America/New_York) as UTC and showed every time four hours
    early."""
    report = build_report(onecall)
    assert report["current"]["sunrise"] == "7:38 AM"
    assert report["current"]["sunset"] == "7:10 PM"
    assert report["current"]["updated"] == "1:26 PM"
    assert report["hourly"][0]["label"] == "2 PM"
    assert report["daily"][0]["sunrise"] == "7:38 AM"


def test_times_follow_the_responses_offset(onecall):
    onecall["timezone_offset"] = 3600
    report = build_report(onecall)
    assert report["current"]["sunrise"] == "12:38 PM"
    assert report["current"]["sunset"] == "12:10 AM"
    assert report["hourly"][0]["label"] == "7 PM"


def test_times_dont_depend_on_the_process_zone(onecall):
    before = os.environ.get("TZ")
    os.environ["TZ"] = "Asia/Tokyo"
    time.tzset()
    try:
        report = build_report(onecall)
    finally:
        if before is None:
            del os.environ["TZ"]
        else:
            os.environ["TZ"] = before
        time.tzset()
    assert report["current"]["sunrise"] == "7:38 AM"
    assert report["hourly"][0]["label"] == "2 PM"


def test_without_an_offset_times_are_utc(onecall):
    del onecall["timezone_offset"]
    assert build_report(onecall)["current"]["sunrise"] == "11:38 AM"


# build_report: the rest


def test_current(onecall):
    current = build_report(onecall)["current"]
    assert current["temp"] == 64
    assert current["feels_like"] == 64
    assert current["description"] == "overcast clouds"
    assert current["icon"] == "cloudy"
    assert current["owm_icon"] == "04d"
    assert current["high"] == round(onecall["daily"][0]["temp"]["max"]) == 65
    assert current["low"] == round(onecall["daily"][0]["temp"]["min"]) == 60
    assert current["wind_speed"] == 13
    assert current["wind_dir"] == "ENE"
    assert current["wind_gust"] == 28
    assert current["uv_level"] == "low"
    assert current["visibility"] == 1.9


def test_pop_is_an_integer_percent(onecall):
    report = build_report(onecall)
    assert report["current"]["pop"] == 100
    for row in report["hourly"] + report["daily"]:
        assert isinstance(row["pop"], int)
        assert 0 <= row["pop"] <= 100
    assert report["hourly"][0]["pop"] == round(onecall["hourly"][1]["pop"] * 100)


def test_hourly_skips_the_current_hour(onecall):
    hourly = build_report(onecall)["hourly"]
    assert len(hourly) == 24
    assert hourly[0]["temp"] == round(onecall["hourly"][1]["temp"])
    assert hourly[-1]["temp"] == round(onecall["hourly"][24]["temp"])


def test_hourly_marks_the_new_day(onecall):
    hourly = build_report(onecall)["hourly"]
    new_days = [i for i, row in enumerate(hourly) if row["new_day"]]
    assert new_days == [10]
    assert hourly[10]["label"] == "12 AM"
    assert hourly[10]["day"] == "Sunday"
    assert all(row["day"] == "" for row in hourly[:10])
    assert all(row["day"] == "Sunday" for row in hourly[10:])


def test_daily(onecall):
    daily = build_report(onecall)["daily"]
    assert len(daily) == 8
    assert daily[0]["name"] == "Today"
    assert daily[0]["date"] == "Oct 10"
    assert daily[1]["name"] == "Sunday"
    assert daily[1]["date"] == "Oct 11"
    assert daily[0]["high"] == 65
    assert daily[0]["low"] == 60
    assert all(row["moon_phase"] for row in daily)


def test_next_hour_from_the_response(onecall):
    next_hour = build_report(onecall)["next_hour"]
    # the sample's current weather is Clouds, so the word is "precipitation"
    assert next_hour["wet"] is True
    assert "precipitation" in next_hour["text"].lower()


def test_without_minutely_or_alerts(onecall):
    del onecall["minutely"]
    del onecall["alerts"]
    report = build_report(onecall)
    assert report["next_hour"] is None
    assert report["alerts"] == []


def test_alerts_until(onecall):
    alerts = build_report(onecall)["alerts"]
    assert [a["event"] for a in alerts] == [
        "Tropical Cyclone Local Statement",
        "Flood Watch",
        "High Wind Warning",
    ]
    assert alerts[0]["until"] == "until 1:30 PM today"
    assert alerts[1]["until"] == "until 8 AM Sunday"
    assert alerts[2]["until"] == "until 8 AM Sunday"
    assert alerts[0]["sender"] == onecall["alerts"][0]["sender_name"]
    assert alerts[0]["description"]


def test_alerts_sorted_by_start(onecall):
    onecall["alerts"].reverse()
    events = [a["event"] for a in build_report(onecall)["alerts"]]
    assert events == [
        "Tropical Cyclone Local Statement",
        "Flood Watch",
        "High Wind Warning",
    ]


def test_alerts_deduplicated(onecall):
    onecall["alerts"].append(copy.deepcopy(onecall["alerts"][1]))
    onecall["alerts"].insert(0, copy.deepcopy(onecall["alerts"][2]))
    assert len(build_report(onecall)["alerts"]) == 3


def test_alert_without_end(onecall):
    del onecall["alerts"][0]["end"]
    assert build_report(onecall)["alerts"][0]["until"] == ""


# report_for


@pytest.mark.django_db
def test_report_for_without_a_location(user):
    with patch(GET) as get:
        assert report_for(user) is None
    get.assert_not_called()


@pytest.mark.django_db
def test_report_for(user, onecall):
    user.weather_lat, user.weather_lon = 36.85, -76.29
    with patch(GET, return_value=api_response(onecall)):
        report = report_for(user)
    assert report["current"]["sunrise"] == "7:38 AM"


@pytest.mark.django_db
def test_report_for_when_the_api_fails(user):
    user.weather_lat, user.weather_lon = 36.85, -76.29
    with patch(GET, side_effect=requests.ConnectionError):
        assert report_for(user) is None


# ---------------------------------------------------------------------------
# clearing alerts
# ---------------------------------------------------------------------------


def test_alert_key_names_the_event_and_its_span():
    from apps.weather.service import alert_key

    alert = {"event": "Flood Watch", "start": 100, "end": 200}
    assert alert_key(alert) == "Flood Watch|100|200"


def test_build_report_leaves_out_dismissed_alerts(onecall):
    from apps.weather.service import alert_key, build_report

    first = alert_key(onecall["alerts"][0])
    report = build_report(onecall, dismissed=[first])
    assert first not in [alert["key"] for alert in report["alerts"]]
    assert len(report["alerts"]) == len(build_report(onecall)["alerts"]) - 1


@pytest.mark.django_db
def test_dismiss_alert_keeps_the_key_and_forgets_ended_alerts(user):
    from datetime import datetime, timedelta, timezone

    from apps.weather.service import dismiss_alert

    future = int((datetime.now(timezone.utc) + timedelta(days=1)).timestamp())
    past = int((datetime.now(timezone.utc) - timedelta(days=1)).timestamp())
    user.weather_dismissed_alerts = [f"Old Watch|1|{past}", f"Wind|1|{future}"]
    user.save()
    dismiss_alert(user, f"Flood Watch|2|{future}")
    user.refresh_from_db()
    assert user.weather_dismissed_alerts == [
        f"Wind|1|{future}",
        f"Flood Watch|2|{future}",
    ]
    # clearing the same alert twice keeps one key
    dismiss_alert(user, f"Flood Watch|2|{future}")
    user.refresh_from_db()
    assert user.weather_dismissed_alerts.count(f"Flood Watch|2|{future}") == 1


def test_wind_text_reads_as_one_phrase():
    from apps.weather.service import wind

    assert (
        wind({"wind_speed": 20.6, "wind_deg": 70, "wind_gust": 42.3})["wind_text"]
        == "21 mph ENE, gusts 42"
    )
    assert wind({"wind_speed": 5.2, "wind_deg": 180})["wind_text"] == "5 mph S"


def test_current_rain_and_snow_rates(onecall):
    from apps.weather.service import build_report

    assert build_report(onecall)["current"]["rain_rate"] == ""
    onecall["current"]["rain"] = {"1h": 2.54}
    onecall["current"]["snow"] = {"1h": 0.3}
    current = build_report(onecall)["current"]
    assert current["rain_rate"] == "0.1"
    assert current["snow_rate"] == "<0.1"


@pytest.mark.parametrize(
    "hpa, tone, level",
    [
        (980, "very-low", "Very low"),
        (1000, "low", "Low"),
        (1013, "average", "Near average"),
        (1021, "average", "Near average"),
        (1025, "high", "High"),
        (1040, "very-high", "Very high"),
    ],
)
def test_pressure_bands(hpa, tone, level):
    from apps.weather.service import pressure

    reading = pressure(hpa)
    assert (reading["pressure_tone"], reading["pressure_level"]) == (tone, level)
    assert reading["pressure_from_average"] == hpa - 1013


def test_pressure_in_inches_of_mercury_and_absent():
    from apps.weather.service import pressure

    assert pressure(1013)["pressure_inhg"] == "29.91"
    assert pressure(1013)["pressure_relative"] == "the 1013 average"
    assert pressure(1012)["pressure_relative"] == "1 below the 1013 average"
    assert pressure(1030)["pressure_relative"] == "17 above the 1013 average"
    assert pressure(None) == {}


def test_short_clock_drops_the_minutes_on_the_hour():
    from datetime import datetime, timezone

    from apps.weather.service import short_clock

    assert short_clock(datetime(2026, 10, 11, 8, 0, tzinfo=timezone.utc)) == "8 AM"
    assert short_clock(datetime(2026, 10, 11, 13, 30, tzinfo=timezone.utc)) == "1:30 PM"


def test_reflow_joins_wrapped_lines_but_keeps_paragraphs_and_items():
    from apps.weather.service import reflow

    text = (
        "* WHAT...Flooding caused by excessive rainfall continues to be\n"
        "possible.\n\n"
        "* WHERE...Portions of central Georgia,\n"
        "including Fulton.\n"
        "- http://www.weather.gov/safety/flood"
    )
    assert reflow(text) == (
        "* WHAT...Flooding caused by excessive rainfall continues to be possible.\n\n"
        "* WHERE...Portions of central Georgia, including Fulton.\n"
        "- http://www.weather.gov/safety/flood"
    )


# ---------------------------------------------------------------------------
# units
# ---------------------------------------------------------------------------


def test_metric_report_converts_every_measure(onecall):
    from apps.weather.service import build_report

    imperial = build_report(onecall)
    metric = build_report(onecall, units="metric")
    assert metric["units_name"] == "metric"
    assert metric["units"] == {
        "temp": "°C",
        "speed": "km/h",
        "precip": "mm",
        "distance": "km",
    }
    # 64.17 °F is 17.9 °C; 12.66 mph is 20.4 km/h; 3114 m is 3.1 km
    assert (imperial["current"]["temp"], metric["current"]["temp"]) == (64, 18)
    assert (imperial["current"]["wind_speed"], metric["current"]["wind_speed"]) == (
        13,
        20,
    )
    assert metric["current"]["wind_text"].startswith("20 km/h")
    assert (imperial["current"]["visibility"], metric["current"]["visibility"]) == (
        1.9,
        3.1,
    )
    assert metric["current"]["pressure_inhg"] == ""
    assert imperial["current"]["pressure_inhg"] != ""
    # the day's rain is 25.08 mm: an inch to an imperial reader
    assert (imperial["daily"][0]["precip"], metric["daily"][0]["precip"]) == (
        "1.0",
        "25.1",
    )
    assert metric["hourly"][0]["temp"] == round(
        (onecall["hourly"][1]["temp"] - 32) * 5 / 9
    )
    assert metric["daily"][2]["high"] == round(
        (onecall["daily"][2]["temp"]["max"] - 32) * 5 / 9
    )


def test_unknown_units_read_as_imperial(onecall):
    from apps.weather.service import build_report

    assert build_report(onecall, units="furlongs")["units_name"] == "imperial"


def test_amount_in_millimetres():
    from apps.weather.service import amount

    assert amount(0.5, "metric") == "0.5"
    assert amount(0.02, "metric") == "<0.1"
    assert amount(None, "metric") == ""
