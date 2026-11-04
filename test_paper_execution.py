import pytest

from batch_entry import EntryCandidate, PortfolioLimits, ValidatedEntry
from paper_execution import recompute_paper_execution


def candidate(side="BUY", price=100.0):
    return EntryCandidate("AAA", side, price, 99.0, 98.0, {})


def entry(side="BUY", stop=99.0, target=103.0, confidence=0.9):
    return ValidatedEntry("AAA", side, confidence, "aligned breakout", stop, target, 1, 999, 99999.0)


def limits(**overrides):
    values = dict(
        capital=10000.0, available_cash=10000.0, risk_per_trade_pct=1.0,
        max_positions=2, open_positions=0, max_trades_per_day=3,
        trades_today=0, daily_loss_cap_pct=3.0, day_pnl=0.0,
        min_confidence=0.5,
    )
    values.update(overrides)
    return PortfolioLimits(**values)


def test_recomputes_quantity_after_slippage_and_entry_fee():
    plan = recompute_paper_execution(
        entry(), candidate(), limits(), slippage_pct=0.1, cost_pct=0.1
    )
    assert plan is not None
    assert plan.entry_fill == pytest.approx(100.1)
    assert plan.quantity == 90
    assert plan.entry_fee == pytest.approx(4.5045)
    assert plan.risk_amount == pytest.approx(99.0)


def test_sell_execution_uses_adverse_slippage_and_geometry():
    plan = recompute_paper_execution(
        entry("SELL", stop=101.0, target=97.0),
        candidate("SELL"), limits(), slippage_pct=0.1, cost_pct=0.1,
    )
    assert plan is not None
    assert plan.entry_fill == pytest.approx(99.9)
    assert plan.quantity == 90


@pytest.mark.parametrize("snapshot", [
    {"open_positions": 2},
    {"trades_today": 3},
    {"day_pnl": -300.0},
    {"available_cash": 0.0},
])
def test_execution_rechecks_current_portfolio_limits(snapshot):
    assert recompute_paper_execution(
        entry(), candidate(), limits(**snapshot), slippage_pct=0.05, cost_pct=0.1
    ) is None


def test_rejects_side_conflict_and_invalid_post_slippage_geometry():
    assert recompute_paper_execution(
        entry("SELL", stop=101, target=97), candidate("BUY"), limits(),
        slippage_pct=0.05, cost_pct=0.1,
    ) is None
    assert recompute_paper_execution(
        entry(stop=100.11, target=103), candidate(), limits(),
        slippage_pct=0.1, cost_pct=0.1,
    ) is None


@pytest.mark.parametrize("field,value", [
    ("slippage_pct", True), ("cost_pct", float("nan")),
])
def test_rejects_boolean_or_nonfinite_cost_inputs(field, value):
    kwargs = {"slippage_pct": 0.05, "cost_pct": 0.1}
    kwargs[field] = value
    with pytest.raises(ValueError):
        recompute_paper_execution(entry(), candidate(), limits(), **kwargs)


def test_never_trusts_preliminary_ai_quantity():
    proposed = entry()
    object.__setattr__(proposed, "quantity", 999999)
    plan = recompute_paper_execution(
        proposed, candidate(), limits(), slippage_pct=0.05, cost_pct=0.1
    )
    assert plan.quantity < 999999


def test_malformed_fresh_portfolio_snapshot_fails_closed():
    assert recompute_paper_execution(
        entry(), candidate(), limits(open_positions=True),
        slippage_pct=0.05, cost_pct=0.1,
    ) is None
