import pytest
from low_price_universe import LowPriceConfig, LowPriceUniverseError, parse_nse_cash_equities, select_under_25_candidates

def instruments():
    return [{"symbol":"ABC","tradingsymbol":"ABC-EQ","token":"101","exchange":"NSE"}, {"symbol":"XYZ","tradingsymbol":"XYZ-EQ","token":"102","exchange":"NSE"}]

def quote(price="24.50", bid="24.45", ask="24.55", received=1000):
    return {"price":price,"bid":bid,"ask":ask,"received_at":received}

def test_parses_only_unique_nse_cash_eq_rows():
    rows=[{"exch_seg":"nse_cm","symbol":"ABC-EQ","token":"101","tick_size":"0.01"},{"exch_seg":"nse_fo","symbol":"FUT","token":"202"},{"exch_seg":"bse_cm","symbol":"BSE-EQ","token":"303"},{"exch_seg":"nse_cm","symbol":"ABC24JUNFUT","token":"404"}]
    assert [r["symbol"] for r in parse_nse_cash_equities(rows)] == ["ABC"]

def test_rejects_ambiguous_cash_tokens():
    rows=[{"exch_seg":"nse_cm","symbol":"ABC-EQ","token":"101"},{"exch_seg":"nse_cm","symbol":"ABC-EQ","token":"999"}]
    with pytest.raises(LowPriceUniverseError, match="Ambiguous"): parse_nse_cash_equities(rows)

def test_price_ceiling_is_inclusive_and_over_25_is_rejected():
    result=select_under_25_candidates(instruments(),{"ABC":quote("25.00"),"XYZ":quote("25.01")},{"ABC":60_000_000,"XYZ":60_000_000},now_epoch=1000)
    assert [r["symbol"] for r in result] == ["ABC"]

def test_missing_or_wide_spread_fails_closed():
    result=select_under_25_candidates(instruments(),{"ABC":{"price":10,"received_at":1000},"XYZ":quote("10","9.90","10.10")},{"ABC":100_000_000,"XYZ":100_000_000},now_epoch=1000)
    assert result == []

def test_stale_quote_and_low_turnover_are_rejected():
    result=select_under_25_candidates(instruments(),{"ABC":quote(received=900),"XYZ":quote()},{"ABC":100_000_000,"XYZ":49_999_999},now_epoch=1000)
    assert result == []

def test_ranks_by_turnover_and_caps_results():
    result=select_under_25_candidates(instruments(),{"ABC":quote(),"XYZ":quote()},{"ABC":70_000_000,"XYZ":90_000_000},now_epoch=1000,config=LowPriceConfig(max_candidates=1))
    assert [r["symbol"] for r in result] == ["XYZ"]

def test_rejects_invalid_config():
    with pytest.raises(ValueError): LowPriceConfig(max_price=0)
