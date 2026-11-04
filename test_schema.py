"""Schema contract checks that run offline without Supabase credentials."""
from pathlib import Path


def test_paper_trade_schema_has_columns_written_by_bot():
    sql = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8").lower()
    required = (
        "status text",
        "last_price numeric",
        "last_price_ts timestamptz",
        "llm_decision text",
        "llm_reason text",
        "initial_stop numeric",
        "target numeric",
        "ai_confidence numeric",
        "ai_rank integer",
        "create table if not exists manual_exit_requests",
        "create table if not exists orb_bot_settings",
    )
    for column in required:
        assert column in sql, f"schema.sql is missing bot logging column: {column}"
