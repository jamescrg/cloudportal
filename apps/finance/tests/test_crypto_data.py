import pytest

import apps.finance.crypto_data as crypto_data


@pytest.mark.live
def test_fetch():
    symbols = "ALGO,ETH,ATOM,MATIC,BTC"
    data = crypto_data.collect(symbols)
    assert data["BTC"]
    assert data["BTC"]["quote"]["USD"]["market_cap"] > 0
    assert data["MATIC"]["quote"]["USD"]["price"] > 0


def test_condense(sample_crypto_data):
    condensed_data = crypto_data.condense(sample_crypto_data)
    assert "BTC" in condensed_data
    assert "symbol" in condensed_data["BTC"]
    assert "name" in condensed_data["BTC"]


def test_sort(sample_crypto_data):
    condensed_data = crypto_data.condense(sample_crypto_data)
    sorted_data = crypto_data.sort(condensed_data)
    assert sorted_data[0]["symbol"] == "BTC"
    sorted_data = crypto_data.sort(condensed_data, "symbol")
    assert sorted_data[2]["symbol"] == "ETH"
