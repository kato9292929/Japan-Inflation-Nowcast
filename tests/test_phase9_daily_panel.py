"""Phase 9: 食料 日次パネル化のテスト（固定基準日の複数日 Jevons）。

実通信なし・決定的。一時 SQLite。fixtures はライフバスケット day-1(90)/day-2(197)。
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest
from sqlmodel import select

from index_engine import food
from jobs.import_csv import import_csv
from storage.models import FoodClean, FoodRaw, IndexValue

FIX = Path(__file__).resolve().parent / "fixtures"
CSV_04 = str(FIX / "life_basket_20260604.csv")
CSV_05 = str(FIX / "life_basket_20260605.csv")
D04 = date(2026, 6, 4)
D05 = date(2026, 6, 5)


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    db_path = tmp_path / "jin.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("BASE_DATE", "2026-06-04")
    import storage.db as db

    db.get_settings.cache_clear()
    db.get_engine.cache_clear()
    db.init_db()
    yield db
    db.get_settings.cache_clear()
    db.get_engine.cache_clear()


def _clean_panel(db) -> pd.DataFrame:
    with db.get_session() as s:
        rows = s.exec(select(FoodClean)).all()
    return pd.DataFrame(
        [
            {
                "scrape_date": r.scrape_date,
                "sku_key": r.sku_key,
                "unit_price": r.unit_price,
                "category": r.category,
                "is_promo": r.is_promo,
            }
            for r in rows
        ]
    )


def _import_both(db) -> None:
    import_csv(CSV_04, scrape_date=D04, kind="food")
    import_csv(CSV_05, scrape_date=D05, kind="food")


# --------------------------------------------------------------------------- #
# 1) 両日のパネルが保持される
# --------------------------------------------------------------------------- #
def test_panel_preserves_both_days(tmp_db) -> None:
    _import_both(tmp_db)
    with tmp_db.get_session() as s:
        raw = s.exec(select(FoodRaw)).all()
        clean = s.exec(select(FoodClean)).all()

    # day-1=90 行 + day-2=197 行（日付が違うので全て別行）。
    assert len(raw) == 90 + 197
    assert len(clean) == 90 + 197

    def dates(rows, item_id):
        return sorted(str(r.scrape_date) for r in rows if r.item_id == item_id)

    # 共通 SKU は 2 行（両日）。
    assert dates(raw, "L001") == ["2026-06-04", "2026-06-05"]
    # day-1 のみ SKU（day-2 で消失）は 1 行（06-04）。
    assert dates(raw, "L005") == ["2026-06-04"]
    # day-2 のみ SKU（新規）は 1 行（06-05）。
    assert dates(raw, "L091") == ["2026-06-05"]


# --------------------------------------------------------------------------- #
# 2) 同一日付の再ランは冪等（行が増えない）
# --------------------------------------------------------------------------- #
def test_idempotent_same_date(tmp_db) -> None:
    import_csv(CSV_04, scrape_date=D04, kind="food")
    with tmp_db.get_session() as s:
        n1 = len(s.exec(select(FoodRaw)).all())
    import_csv(CSV_04, scrape_date=D04, kind="food")  # 同じ records を再投入
    with tmp_db.get_session() as s:
        n2 = len(s.exec(select(FoodRaw)).all())
        nc = len(s.exec(select(FoodClean)).all())
    assert n1 == 90
    assert n2 == 90  # 複合 unique 制約で更新 → 増えない
    assert nc == 90


# --------------------------------------------------------------------------- #
# 3) snapshot が日付ごとに独立した SKU セットを返す
# --------------------------------------------------------------------------- #
def test_snapshot_isolation(tmp_db) -> None:
    _import_both(tmp_db)
    df = _clean_panel(tmp_db)

    snap04 = food._snapshot(df, on=D04, promo_mode="incl_promo")
    snap05 = food._snapshot(df, on=D05, promo_mode="incl_promo")
    # promo フィルタ無し → 行数 = 各日の入力 records 数。
    assert len(snap04) == 90
    assert len(snap05) == 197
    # 日付混在なし。
    assert set(pd.to_datetime(snap04["scrape_date"]).dt.date) == {D04}
    assert set(pd.to_datetime(snap05["scrape_date"]).dt.date) == {D05}


# --------------------------------------------------------------------------- #
# 4) Jevons の対称性: rel_forward * rel_backward ≈ 1
# --------------------------------------------------------------------------- #
def test_jevons_symmetry(tmp_db) -> None:
    _import_both(tmp_db)
    df = _clean_panel(tmp_db)

    snap04 = food._snapshot(df, on=D04, promo_mode="excl_promo")
    snap05 = food._snapshot(df, on=D05, promo_mode="excl_promo")
    bp04 = food._base_prices(snap04)
    bp05 = food._base_prices(snap05)

    fwd = food.jevons_elementary(snap05, base_prices=bp04)  # 05/04
    bwd = food.jevons_elementary(snap04, base_prices=bp05)  # 04/05

    common = set(fwd) & set(bwd)
    assert common
    for c in common:
        assert fwd[c] * bwd[c] == pytest.approx(1.0, abs=1e-9)


# --------------------------------------------------------------------------- #
# 5) 棚落ち後のライフサイクル
# --------------------------------------------------------------------------- #
def test_lifecycle_after_dropout(tmp_db) -> None:
    _import_both(tmp_db)
    with tmp_db.get_session() as s:
        rows = s.exec(select(FoodRaw)).all()
    by_id: dict[str, list] = {}
    for r in rows:
        by_id.setdefault(r.item_id, []).append(r)

    # day-1 のみ（消失）: 全行 inactive、first=last=06-04。
    drop = by_id["L005"]
    assert all(r.is_active is False for r in drop)
    assert all(r.first_seen == D04 and r.last_seen == D04 for r in drop)

    # 両日: 2 行とも active、first=06-04 / last=06-05。
    both = by_id["L001"]
    assert len(both) == 2
    assert all(r.is_active is True for r in both)
    assert all(r.first_seen == D04 and r.last_seen == D05 for r in both)

    # day-2 のみ（新規）: active、first=last=06-05。
    new = by_id["L091"]
    assert all(r.is_active is True for r in new)
    assert all(r.first_seen == D05 and r.last_seen == D05 for r in new)


# --------------------------------------------------------------------------- #
# 6) 実データ day-2 値（daily.run 経由で index_values に保存）
# --------------------------------------------------------------------------- #
def test_real_day2_values(tmp_db, monkeypatch, tmp_path) -> None:
    from jobs import daily

    _import_both(tmp_db)
    # スクレイプ無し（CSV import 済み）。
    monkeypatch.setattr(daily, "load_sources", lambda kind: [])

    rc = daily.run(as_of=D05, methodology_path=tmp_path / "m.md")
    assert rc == 0

    with tmp_db.get_session() as s:
        def get(code, stype=None):
            q = select(IndexValue).where(IndexValue.index_code == code, IndexValue.date == D05)
            if stype:
                q = q.where(IndexValue.series_type == stype)
            return s.exec(q).first()

        excl = get("JP-INFL-FOOD", "food_excl_promo")
        incl = get("JP-INFL-FOOD", "food_incl_promo")
        nowcast = get("JP-INFL-NOWCAST")

    assert excl is not None and incl is not None and nowcast is not None
    assert excl.value == pytest.approx(100.8157, abs=0.001)
    assert excl.n == 51
    assert incl.value == pytest.approx(99.2564, abs=0.001)
    assert incl.n == 66
    assert nowcast.value == pytest.approx(100.8157, abs=0.001)
    assert nowcast.coverage_pct == pytest.approx(26.26, abs=0.01)
    assert nowcast.series_type == "composite_partial"
