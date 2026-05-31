"""Phase 3 受け入れ条件のテスト（食料スクレイパ + ETL, §6-2, §8）。

実通信なし・決定的。DB は一時 SQLite（fresh_db フィクスチャ）。
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from sqlmodel import select

from etl import food as etl_food
from scrapers.base import SourceConfig
from scrapers.food import ExampleFoodScraper
from storage.models import FoodClean, FoodRaw

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "food_example.html"
DAY1 = date(2025, 1, 1)
DAY2 = date(2025, 1, 2)


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


def _scraper() -> ExampleFoodScraper:
    return ExampleFoodScraper(
        SourceConfig(id="example", base_url="https://example.test", enabled=True),
        user_agent="JapanInflationNowcastBot/test",
        contact="ops@example.com",
        sleeper=lambda _s: None,
    )


def _item(item_id: str, **fields) -> dict:
    base = {"source": "example", "item_id": item_id}
    base.update(fields)
    return base


# --------------------------------------------------------------------------- #
# 1) parse
# --------------------------------------------------------------------------- #
def test_parse_fixture_extracts_records() -> None:
    html = FIXTURE.read_text(encoding="utf-8")
    records = _scraper().parse(html, source_path="/list")

    assert len(records) == 5  # item_id 欠落の 1 件はスキップ
    by_id = {r["item_id"]: r for r in records}

    f1 = by_id["F001"]
    assert f1["category"] == "穀類"
    assert f1["unit"] == "kg"
    assert f1["unit_size"] == 2.0
    assert f1["price"] == 1000.0
    assert f1["is_promo"] is False
    assert f1["in_stock"] is True

    f4 = by_id["F004"]
    assert f4["is_promo"] is True  # 特売
    assert f4["unit"] == "g"
    assert f4["unit_size"] == 100.0

    assert by_id["F005"]["in_stock"] is False


# --------------------------------------------------------------------------- #
# 2) pipeline: sku_key + unit_price（単位換算込み）
# --------------------------------------------------------------------------- #
def test_pipeline_builds_clean_with_unit_price(fresh_db) -> None:
    html = FIXTURE.read_text(encoding="utf-8")
    records = _scraper().parse(html, source_path="/list")

    assert etl_food.upsert_raw(records, scrape_date=DAY1) == 5
    assert etl_food.run(scrape_date=DAY1) == 5

    with fresh_db.get_session() as s:
        clean = {r.item_id: r for r in s.exec(select(FoodClean)).all()}

    assert clean["F001"].unit_price == pytest.approx(50.0)   # kg -> ¥/100g
    assert clean["F002"].unit_price == pytest.approx(20.0)   # l  -> ¥/100ml
    assert clean["F003"].unit_price == pytest.approx(25.0)   # 個 -> ¥/個
    assert clean["F004"].unit_price == pytest.approx(150.0)  # g  -> ¥/100g
    assert clean["F005"].unit_price == pytest.approx(24.0)   # ml -> ¥/100ml

    # sku_key は brand|product_name|unit-family（質量は mass に畳む）。
    assert clean["F001"].sku_key == "農協|コシヒカリ|mass"
    assert clean["F001"].category == "穀類"  # CPI 中分類を保持


# --------------------------------------------------------------------------- #
# 3) 同一 SKU を時系列追跡（item_id が変わっても同一 sku_key）
# --------------------------------------------------------------------------- #
def test_same_sku_tracked_across_days(fresh_db) -> None:
    # day1: item_id=A1, price=100。day2: 同一商品だが source 側 ID が A2 に変化, price=110。
    day1 = [_item("A1", brand="X", product_name="Y", unit="g", unit_size=100, price=100)]
    day2 = [_item("A2", brand="X", product_name="Y", unit="g", unit_size=100, price=110)]

    etl_food.upsert_raw(day1, scrape_date=DAY1)
    etl_food.run(scrape_date=DAY1)
    etl_food.upsert_raw(day2, scrape_date=DAY2)
    etl_food.run(scrape_date=DAY2)

    with fresh_db.get_session() as s:
        clean = {r.item_id: r for r in s.exec(select(FoodClean)).all()}

    # 両 item_id が同一 sku_key に落ちる（時系列同定）。
    assert clean["A1"].sku_key == clean["A2"].sku_key == "x|y|mass"
    # 各日の unit_price が価格変化を反映（Phase 4 が価格相対を取れる状態）。
    assert clean["A1"].unit_price == pytest.approx(100.0)
    assert clean["A2"].unit_price == pytest.approx(110.0)


# --------------------------------------------------------------------------- #
# 4) 冪等性
# --------------------------------------------------------------------------- #
def test_idempotent_reruns_do_not_duplicate(fresh_db) -> None:
    html = FIXTURE.read_text(encoding="utf-8")
    records = _scraper().parse(html, source_path="/list")

    for _ in range(2):
        etl_food.upsert_raw(records, scrape_date=DAY1)
        etl_food.run(scrape_date=DAY1)

    with fresh_db.get_session() as s:
        n_raw = len(s.exec(select(FoodRaw)).all())
        n_clean = len(s.exec(select(FoodClean)).all())
    assert n_raw == 5
    assert n_clean == 5


# --------------------------------------------------------------------------- #
# 5) ライフサイクル（棚落ち / first_seen 保持 / last_seen 更新）
# --------------------------------------------------------------------------- #
def test_lifecycle_first_last_seen_and_exit(fresh_db) -> None:
    day1 = [
        _item("A", brand="X", product_name="a", unit="g", unit_size=100, price=100),
        _item("B", brand="X", product_name="b", unit="g", unit_size=100, price=200),
        _item("C", brand="X", product_name="c", unit="g", unit_size=100, price=300),
    ]
    day2 = [
        _item("A", brand="X", product_name="a", unit="g", unit_size=100, price=120),
        _item("B", brand="X", product_name="b", unit="g", unit_size=100, price=200),
    ]

    etl_food.upsert_raw(day1, scrape_date=DAY1)
    etl_food.upsert_raw(day2, scrape_date=DAY2)

    with fresh_db.get_session() as s:
        rows = {r.item_id: r for r in s.exec(select(FoodRaw)).all()}

    assert rows["C"].is_active is False
    assert rows["C"].first_seen == DAY1
    for iid in ("A", "B"):
        assert rows[iid].is_active is True
        assert rows[iid].first_seen == DAY1
        assert rows[iid].last_seen == DAY2
    assert rows["A"].price == 120.0


# --------------------------------------------------------------------------- #
# 6) 特売保持（Phase 4 incl/excl promo の前提）
# --------------------------------------------------------------------------- #
def test_promo_flag_retained_in_clean(fresh_db) -> None:
    html = FIXTURE.read_text(encoding="utf-8")
    records = _scraper().parse(html, source_path="/list")
    etl_food.upsert_raw(records, scrape_date=DAY1)
    etl_food.run(scrape_date=DAY1)

    with fresh_db.get_session() as s:
        clean = {r.item_id: r for r in s.exec(select(FoodClean)).all()}

    assert clean["F004"].is_promo is True
    assert clean["F001"].is_promo is False
