import pandas as pd
import bot


def _df(vols):
    idx = pd.date_range("2026-11-10 09:15", periods=len(vols), freq="1min")
    return pd.DataFrame({"Volume": vols}, index=idx)


def test_auction_bar_and_partial_last_bar_do_not_skew_ratio():
    vols = [1_000_000] + [1000] * 28 + [5]   # huge auction bar, partial last bar
    assert bot.volume_surge_ratio(_df(vols)) == 1.0


def test_surge_detected():
    vols = [1_000_000] + [1000] * 20 + [3000] * 5 + [10]
    assert bot.volume_surge_ratio(_df(vols)) == 3.0


def test_too_little_data_returns_none():
    assert bot.volume_surge_ratio(_df([1, 2, 3])) is None
    assert bot.volume_surge_ratio(None) is None
