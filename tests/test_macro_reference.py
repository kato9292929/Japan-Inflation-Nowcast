"""macro_reference ストア + CGPI fetcher のテスト（実通信なし・fixture 使用）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from lib import macro_reference

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "cgpi_sample.csv"


# --------------------------------------------------------------------------- #
# 必須ユニットテスト: 空 parquet で None
# --------------------------------------------------------------------------- #
def test_get_latest_value_empty_returns_none(tmp_path) -> None:
    empty = tmp_path / "macro_reference.parquet"  # 存在しない
    assert macro_reference.get_latest_value("cgpi_total", path=empty) is None


def test_upsert_and_get_latest(tmp_path) -> None:
    import scripts.fetch_cgpi as fetch

    pq = tmp_path / "macro_reference.parquet"
    parsed = fetch.parse_cgpi(FIXTURE.read_text(encoding="utf-8"))
    rows = fetch.to_rows(parsed)
    macro_reference.upsert(rows, path=pq)

    latest = macro_reference.get_latest_value("cgpi_total", "yoy_pct", path=pq)
    assert latest is not None
    assert latest["period"] == "2026-05"
    assert latest["value"] == 6.3
    assert latest["release_type"] == "flash"

    latest_level = macro_reference.get_latest_value("cgpi_total", "level", path=pq)
    assert latest_level["period"] == "2026-05"
    assert latest_level["value"] == 134.5


def test_upsert_idempotent(tmp_path) -> None:
    import scripts.fetch_cgpi as fetch

    pq = tmp_path / "macro_reference.parquet"
    rows = fetch.to_rows(fetch.parse_cgpi(FIXTURE.read_text(encoding="utf-8")))
    n1 = macro_reference.upsert(rows, path=pq)
    n2 = macro_reference.upsert(rows, path=pq)
    assert n1 == n2  # 同一自然キーの再投入で行数は増えない
    assert n1 == 24 * 2  # 24 ヶ月 × (level, yoy_pct)


def test_parse_cgpi_known_values() -> None:
    import scripts.fetch_cgpi as fetch

    parsed = fetch.parse_cgpi(FIXTURE.read_text(encoding="utf-8"))
    assert len(parsed) >= 12
    apr = parsed[parsed["period"] == "2026-04"].iloc[0]
    assert apr["yoy_pct"] == 5.3
    assert apr["release_type"] == "final"
    may = parsed[parsed["period"] == "2026-05"].iloc[0]
    assert may["level"] == 134.5 and may["yoy_pct"] == 6.3
    assert may["release_type"] == "flash"


def test_parse_cgpi_raises_on_bad_format() -> None:
    import scripts.fetch_cgpi as fetch

    with pytest.raises(ValueError):
        fetch.parse_cgpi("# only metadata\n\nfoo,bar\n1,2\n")
