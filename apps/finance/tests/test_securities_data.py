import pytest

import apps.finance.securities_data as securities_data

pytestmark = pytest.mark.live


def test_fetch():
    symbol = "GME"
    data = securities_data.fetch(symbol)
    keys = "c dp h l o pc t".split(" ")
    for key in keys:
        assert key in data
    assert data["c"] > 0


def test_collect():
    assets = securities_data.asset_list
    data = securities_data.collect(assets)
    assert "symbol" in data[0]
    assert "open" in data[0]
    assert "exchange" in data[0]
    assert len(data) == len(assets)


def test_sort():
    assets = securities_data.asset_list
    data = securities_data.collect(assets)
    sorted_data = securities_data.sort(data, "symbol")
    assert sorted_data[0]["symbol"] == "BBBY"
    assert sorted_data[-1]["symbol"] == "VTV"
    sorted_data = securities_data.sort(data, "name")
    assert sorted_data[0]["name"] == "BBBY"
    assert sorted_data[-1]["name"] == "Vanguard Value"
