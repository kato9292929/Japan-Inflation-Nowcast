"""macro_reference ストア + CGPI mtshtml fetcher のテスト（実通信なし・HTML fixture 使用）。"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from lib import macro_reference

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "cgpi_mtshtml_sample.html"


def _html() -> str:
    return FIXTURE.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# 必須ユニットテスト: 空 parquet で None
# --------------------------------------------------------------------------- #
def test_get_latest_value_empty_returns_none(tmp_path) -> None:
    empty = tmp_path / "macro_reference.parquet"  # 存在しない
    assert macro_reference.get_latest_value("cgpi_total", path=empty) is None


# --------------------------------------------------------------------------- #
# parse: mtshtml テーブル -> level/yoy（系列コードで列選択）
# --------------------------------------------------------------------------- #
def test_parse_mtshtml_known_values() -> None:
    import scripts.fetch_cgpi as fetch

    parsed = fetch.parse_mtshtml_table(_html())
    assert len(parsed) == 14  # 2025/04..2026/05
    assert parsed["period"].min() == pd.Timestamp("2025-04-01")
    assert parsed["period"].max() == pd.Timestamp("2026-05-01")

    by_period = parsed.set_index(parsed["period"].dt.strftime("%Y-%m"))
    # 国内 level は col4、yoy は col1 → 位置ではなくコードで正しく選べていること。
    assert by_period.loc["2026-05", "level"] == 134.5
    assert by_period.loc["2026-05", "yoy_pct"] == 6.3
    assert by_period.loc["2026-04", "level"] == 133.3
    assert by_period.loc["2026-04", "yoy_pct"] == 5.3
    assert by_period.loc["2025-04", "yoy_pct"] == 3.9


def test_norm_code_handles_backslash_keeps_percent() -> None:
    import scripts.fetch_cgpi as fetch

    # 実ページ表記（`_` の前にバックスラッシュ、全角/半角空白あり）を正規化。
    assert fetch._norm_code("PR01'PRCG20\\_2200000000") == "PR01'PRCG20_2200000000"
    assert fetch._norm_code(" PR01'PRCG20\\_2200000000%　") == "PR01'PRCG20_2200000000%"
    # % は保持され、level と yoy は別物のまま（取り違え防止）。
    assert fetch._norm_code(fetch.LEVEL_CODE) != fetch._norm_code(fetch.YOY_CODE)
    assert fetch._norm_code(fetch.YOY_CODE).endswith("%")
    assert not fetch._norm_code(fetch.LEVEL_CODE).endswith("%")


def test_parse_does_not_swap_level_and_yoy() -> None:
    """level（2020=100, ~100超）と yoy（%, 小さい）を取り違えていないこと。"""
    import scripts.fetch_cgpi as fetch

    parsed = fetch.parse_mtshtml_table(_html())
    assert (parsed["level"] > 100).all()      # 指数水準
    assert (parsed["yoy_pct"].abs() < 20).all()  # 前年比 %
    # 同月で level != yoy（同じ列を二重に拾っていない）。
    assert (parsed["level"] != parsed["yoy_pct"]).all()


# --------------------------------------------------------------------------- #
# upsert + get_latest_value（period は date 月初日）
# --------------------------------------------------------------------------- #
def test_upsert_and_get_latest(tmp_path) -> None:
    import scripts.fetch_cgpi as fetch

    pq = tmp_path / "macro_reference.parquet"
    rows = fetch.to_rows(fetch.parse_mtshtml_table(_html()))
    macro_reference.upsert(rows, path=pq)

    latest = macro_reference.get_latest_value("cgpi_total", "yoy_pct", path=pq)
    assert latest is not None
    assert latest["period"] == date(2026, 5, 1)
    assert latest["value"] == 6.3
    assert latest["release_type"] == "mtshtml"

    level = macro_reference.get_latest_value("cgpi_total", "level", path=pq)
    assert level["period"] == date(2026, 5, 1)
    assert level["value"] == 134.5


def test_upsert_idempotent(tmp_path) -> None:
    import scripts.fetch_cgpi as fetch

    pq = tmp_path / "macro_reference.parquet"
    rows = fetch.to_rows(fetch.parse_mtshtml_table(_html()))
    n1 = macro_reference.upsert(rows, path=pq)
    n2 = macro_reference.upsert(rows, path=pq)
    assert n1 == n2 == 14 * 2  # 14ヶ月 ×（level, yoy_pct）、再投入で増えない


# --------------------------------------------------------------------------- #
# 改訂値の上書き: 同 period の値が変わったら overwrite される
# --------------------------------------------------------------------------- #
def test_revision_overwrites_same_period(tmp_path) -> None:
    import scripts.fetch_cgpi as fetch

    pq = tmp_path / "macro_reference.parquet"
    rows = fetch.to_rows(fetch.parse_mtshtml_table(_html()))
    macro_reference.upsert(rows, path=pq)

    # 2026-04 の yoy が訂正値 5.3 -> 5.9 に改訂されたケースを再投入。
    revised = pd.DataFrame(
        [
            {
                "source": "boj", "series_id": "cgpi_total",
                "period": pd.Timestamp("2026-04-01"), "value": 5.9,
                "metric": "yoy_pct", "release_type": "mtshtml",
                "fetched_at": macro_reference.now_iso(),
            }
        ],
        columns=macro_reference.COLUMNS,
    )
    n_after = macro_reference.upsert(revised, path=pq)

    assert n_after == 14 * 2  # 行数は増えない（同一自然キーで上書き）
    df = macro_reference.load(pq)
    apr = df[(df["period"] == pd.Timestamp("2026-04-01")) & (df["metric"] == "yoy_pct")]
    assert len(apr) == 1
    assert apr.iloc[0]["value"] == 5.9  # 改訂値で上書きされている


# --------------------------------------------------------------------------- #
# フォーマット不一致 / 未実装ソース
# --------------------------------------------------------------------------- #
def test_parse_raises_on_bad_format() -> None:
    import scripts.fetch_cgpi as fetch

    bad = "<html><body><table><tr><td>foo</td><td>bar</td></tr>" \
          "<tr><td>1</td><td>2</td></tr></table></body></html>"
    with pytest.raises(ValueError):
        fetch.parse_mtshtml_table(bad)


def test_bulk_source_not_implemented() -> None:
    import scripts.fetch_cgpi as fetch

    with pytest.raises(NotImplementedError):
        fetch._load_source_html("bulk")
