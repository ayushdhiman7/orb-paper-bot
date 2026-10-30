"""Validated Phase 2 runtime settings. Values are read from environment at process start."""
from dataclasses import dataclass
import os


def _int(name, default, minimum=1):
    value = int(os.getenv(name, str(default)))
    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return value


def _float(name, default, minimum=0.0, maximum=None):
    value = float(os.getenv(name, str(default)))
    if value < minimum or (maximum is not None and value > maximum):
        raise ValueError(f"{name} is outside its allowed range")
    return value


@dataclass(frozen=True)
class Phase2Settings:
    entry_scan_seconds: int = 180
    position_review_seconds: int = 300
    max_positions: int = 2
    risk_per_trade_pct: float = 1.0
    max_gemini_requests_per_day: int = 100
    max_gemini_requests_per_minute: int = 5
    min_ai_confidence: float = 0.65
    max_trades_per_day: int = 3
    daily_loss_cap_pct: float = 3.0
    square_off_time: str = "15:15"
    paper_only: bool = True

    @classmethod
    def from_env(cls):
        return cls(
            entry_scan_seconds=_int("AI_ENTRY_SCAN_SECONDS", 180),
            position_review_seconds=_int("AI_POSITION_REVIEW_SECONDS", 300),
            max_positions=_int("MAX_OPEN_POSITIONS", 2),
            risk_per_trade_pct=_float("RISK_PER_TRADE_PCT", 1.0, 0.01, 1.0),
            max_gemini_requests_per_day=_int("GEMINI_MAX_REQUESTS_PER_DAY", 100),
            max_gemini_requests_per_minute=_int("GEMINI_MAX_REQUESTS_PER_MINUTE", 5),
            min_ai_confidence=_float("AI_MIN_CONFIDENCE", 0.65, 0.0, 1.0),
            max_trades_per_day=_int("MAX_TRADES_PER_DAY", 3),
            daily_loss_cap_pct=_float("DAILY_LOSS_CAP_PCT", 3.0, 0.01, 100.0),
            square_off_time=os.getenv("SQUARE_OFF_TIME", "15:15"),
            paper_only=True,
        )
