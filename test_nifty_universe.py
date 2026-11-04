import json

import pytest

from nifty_universe import (
    EXPECTED_CONSTITUENTS,
    UniverseError,
    build_nifty50_universe,
    parse_angel_master,
    parse_nse_constituents,
    write_universe_cache,
)


def sources():
    symbols = [f"STOCK{i:02d}" for i in range(EXPECTED_CONSTITUENTS)]
    nse = "Constituent list\n\nCompany Name,Industry,Symbol,Series,ISIN Code\n" + "".join(
        f"Company {i},Industry,{symbol},EQ,ISIN{i}\n" for i, symbol in enumerate(symbols)
    )
    angel = [
        {"exch_seg": "nse_cm", "symbol": f"{symbol}-EQ", "token": str(1000 + i)}
        for i, symbol in enumerate(symbols)
    ]
    return symbols, nse, angel


def test_builds_exactly_50_ordered_nse_cash_instruments():
    symbols, nse, angel = sources()
    result = build_nifty50_universe(nse, angel)
    assert len(result) == 50
    assert [item["symbol"] for item in result] == symbols
    assert result[0] == {
        "symbol": symbols[0], "tradingsymbol": f"{symbols[0]}-EQ",
        "token": "1000", "exchange": "NSE",
    }


def test_rejects_incomplete_or_duplicate_constituent_list():
    _, nse, _ = sources()
    with pytest.raises(UniverseError, match="exactly 50"):
        parse_nse_constituents(nse.replace("Company 49,Industry,STOCK49,EQ,ISIN49\n", ""))
    with pytest.raises(UniverseError, match="duplicate"):
        parse_nse_constituents(nse.replace("Company 49,Industry,STOCK49,EQ,ISIN49", "Company 49,Industry,STOCK00,EQ,ISIN49"))


def test_rejects_missing_and_ambiguous_tokens():
    _, nse, angel = sources()
    with pytest.raises(UniverseError, match="Missing Angel One"):
        build_nifty50_universe(nse, angel[:-1])
    with pytest.raises(UniverseError, match="Ambiguous"):
        parse_angel_master(angel + [{"exch_seg": "nse_cm", "symbol": "STOCK00-EQ", "token": "9999"}])


def test_ignores_derivatives_and_other_exchange_segments():
    rows = [
        {"exch_seg": "nse_fo", "symbol": "RELIANCE-EQ", "token": "1"},
        {"exch_seg": "bse_cm", "symbol": "RELIANCE-EQ", "token": "2"},
        {"exch_seg": "nse_cm", "symbol": "RELIANCE24JUNFUT", "token": "3"},
    ]
    assert parse_angel_master(rows) == {}


def test_cache_is_atomic_and_contains_source_metadata(tmp_path):
    _, nse, angel = sources()
    universe = build_nifty50_universe(nse, angel)
    path = tmp_path / "cache" / "nifty50.json"
    write_universe_cache(universe, path)
    saved = json.loads(path.read_text())
    assert len(saved["instruments"]) == 50
    assert saved["source"]["constituents"].startswith("https://")
