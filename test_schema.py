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
    )
    for column in required:
        assert column in sql, f"schema.sql is missing bot logging column: {column}"
