"""実データで surfaced した2点の回帰テスト（食料単位・n 永続化）。

実通信なし・決定的。一時 SQLite。
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest
from sqlmodel import select

from etl import food as etl_food
from index_engine import food as idx_food
from storage.models import FoodClean, IndexValue

BASE_DATE = date(2025, 1, 1)
AS_OF = date(2025, 3, 1)


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    db_path = tmp_path / "jin.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    import storage.db as db

    db.get_settings.cache_clear()
    db.get_engine.cache_clear()
    db.init_db()
    yield db
    db.get_settings.cache_clear()
    db.get_engine.cache_clear()


# --------------------------------------------------------------------------- #
# 1) 個数系単位（束/房/切/株/把/尾）が unit_price を持つ -> Jevons 対象
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("unit", ["束", "房", "切", "株", "把", "尾"])
def test_count_units_get_unit_price(unit: str) -> None:
    rec = {"price": 200.0, "unit_size": 1, "unit": unit}
    up = etl_food.normalize_unit_price(rec)
    assert up is not None  # 黙って脱落しない
    assert up == pytest.approx(200.0)  # ¥/個 系


def test_jevons_includes_count_unit_skus() -> None:
    # 束(野菜) と 房(果物) と 切(魚介) の SKU が matched に乗ること。
    df = pd.DataFrame(
        [
            {"sku_key": "asuparagasu", "unit_price": 210.0, "category": "野菜・海藻"},  # 束 +5%
            {"sku_key": "banana", "unit_price": 110.0, "category": "果物"},              # 房 +10%
            {"sku_key": "shiozake", "unit_price": 105.0, "category": "魚介類"},          # 切 +5%
        ]
    )
    base = {"asuparagasu": 200.0, "banana": 100.0, "shiozake": 100.0}
    elem, counts = idx_food.jevons_elementary(df, base_prices=base, return_counts=True)
    assert counts == {"野菜・海藻": 1, "果物": 1, "魚介類": 1}
    assert elem["野菜・海藻"] == pytest.approx(1.05)
    assert elem["果物"] == pytest.approx(1.10)


# --------------------------------------------------------------------------- #
# 2) daily.run 後、index_values.n が採用SKU数と一致（n_items の永続化）
# --------------------------------------------------------------------------- #
def test_daily_persists_n_items_to_index_n(fresh_db, tmp_path, monkeypatch) -> None:
    from jobs import daily

    # スクレイプ無し（seed のみ）。
    monkeypatch.setattr(daily, "load_sources", lambda kind: [])

    skus = [
        ("brand|a|mass", "穀類", 50.0, 52.5),    # +5%
        ("brand|b|count", "乳卵類", 25.0, 25.0),  # 不変
        ("brand|c|count", "野菜・海藻", 200.0, 210.0),  # 束相当
    ]
    with fresh_db.get_session() as s:
        for i, (sku, cat, base_up, _asof_up) in enumerate(skus):
            s.add(FoodClean(
                item_id=f"base{i}", source="seed", scrape_date=BASE_DATE,
                first_seen=BASE_DATE, last_seen=BASE_DATE, is_active=True,
                category=cat, sku_key=sku, unit_price=base_up, is_promo=False,
            ))
        for i, (sku, cat, _base_up, asof_up) in enumerate(skus):
            s.add(FoodClean(
                item_id=f"asof{i}", source="seed", scrape_date=AS_OF,
                first_seen=AS_OF, last_seen=AS_OF, is_active=True,
                category=cat, sku_key=sku, unit_price=asof_up, is_promo=False,
            ))
        s.commit()

    rc = daily.run(as_of=AS_OF, methodology_path=tmp_path / "m.md")
    assert rc == 0

    with fresh_db.get_session() as s:
        food_idx = s.exec(
            select(IndexValue).where(
                IndexValue.index_code == "JP-INFL-FOOD", IndexValue.date == AS_OF
            )
        ).first()

    assert food_idx is not None
    assert food_idx.n is not None
    assert food_idx.n == 3  # 採用 SKU 数（3 系列すべて matched）
