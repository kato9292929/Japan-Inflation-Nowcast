"""CSV インポータのテスト（公式統計 / 手動パネルのローカル取り込み, §8）。

実通信なし・決定的。一時 SQLite + tests/fixtures の CSV を使う。
列名はわざと日本語の独自名にして column_map 解決を検証する。
"""

from __future__ import annotations

import math
from datetime import date
from pathlib import Path

import pytest
import yaml
from sqlmodel import select

from etl import food as etl_food
from etl import housing as etl_housing
from scrapers.base import SourceConfig
from scrapers.food.csv_import import CsvFoodImporter
from scrapers.housing.csv_import import CsvHousingImporter
from storage.models import FoodClean, FoodRaw, IndexValue, ListingClean

FIXTURES = Path(__file__).resolve().parent / "fixtures"
FOOD_CSV = FIXTURES / "food_panel.csv"
HOUSING_CSV = FIXTURES / "housing_panel.csv"
BASE_DATE = date(2025, 1, 1)
AS_OF = date(2025, 3, 1)

FOOD_MAP = {
    "商品ID": "item_id", "中分類": "category", "商品名": "product_name",
    "メーカー": "brand", "単位": "unit", "内容量": "unit_size", "価格": "price",
    "特売": "is_promo", "在庫": "in_stock",
}
HOUSING_MAP = {
    "物件ID": "listing_id", "区": "ward", "住所": "address_norm", "駅": "station",
    "徒歩分": "walk_min", "家賃": "rent_total", "管理費": "mgmt_fee", "面積": "area_m2",
    "間取り": "madori", "築年": "build_year", "階": "floor", "構造": "structure",
    "敷金": "deposit", "礼金": "key_money",
}


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


def _food_source(path=FOOD_CSV, id="estat_food") -> SourceConfig:
    return SourceConfig(id=id, enabled=True, type="csv", path=str(path), column_map=FOOD_MAP)


def _housing_source(path=HOUSING_CSV) -> SourceConfig:
    return SourceConfig(
        id="manual_housing", enabled=True, type="csv", path=str(path), column_map=HOUSING_MAP
    )


# --------------------------------------------------------------------------- #
# 1) 食料 CSV: 列マッピング・型強制・bool・欠損・raw_payload
# --------------------------------------------------------------------------- #
def test_food_importer_mapping_and_types() -> None:
    records = CsvFoodImporter(_food_source()).run()

    # id 欠落行はスキップ -> 4 件。
    assert len(records) == 4
    by_id = {r["item_id"]: r for r in records}

    f1 = by_id["F001"]
    assert f1["source"] == "estat_food"
    assert f1["category"] == "穀類"
    assert f1["unit"] == "kg"
    assert f1["unit_size"] == 2.0 and isinstance(f1["unit_size"], float)
    assert f1["price"] == 1000.0  # カンマ除去
    assert f1["is_promo"] is False and isinstance(f1["is_promo"], bool)
    assert f1["in_stock"] is True
    # 監査用に元行を保持。
    assert f1["raw_payload"]["商品ID"] == "F001"

    assert by_id["F003"]["is_promo"] is True  # 特売
    # 欠損セルは None 許容。
    assert by_id["F004"]["price"] is None


# --------------------------------------------------------------------------- #
# 2) 食料 CSV -> upsert_raw -> etl.food.run -> food_clean（sku_key/unit_price）
# --------------------------------------------------------------------------- #
def test_food_csv_pipeline_to_clean(fresh_db) -> None:
    records = CsvFoodImporter(_food_source()).run()
    assert etl_food.upsert_raw(records, scrape_date=AS_OF) == 4
    assert etl_food.run(scrape_date=AS_OF) == 4

    with fresh_db.get_session() as s:
        clean = {r.item_id: r for r in s.exec(select(FoodClean)).all()}

    assert clean["F001"].unit_price == pytest.approx(50.0)   # kg -> ¥/100g
    assert clean["F002"].unit_price == pytest.approx(25.0)   # 個 -> ¥/個
    assert clean["F001"].sku_key == "農協|コシヒカリ|mass"
    assert clean["F003"].is_promo is True


# --------------------------------------------------------------------------- #
# 3) 住居 CSV -> listings_clean（特徴量）
# --------------------------------------------------------------------------- #
def test_housing_csv_pipeline_to_clean(fresh_db) -> None:
    records = CsvHousingImporter(_housing_source()).run()
    assert len(records) == 2  # id 欠落行スキップ
    assert records[0]["walk_min"] == 5 and isinstance(records[0]["walk_min"], int)
    assert records[0]["rent_total"] == 120000.0

    assert etl_housing.upsert_raw(records, scrape_date=AS_OF) == 2
    assert etl_housing.run(scrape_date=AS_OF, as_of_year=2025) == 2

    with fresh_db.get_session() as s:
        clean = {r.listing_id: r for r in s.exec(select(ListingClean)).all()}

    h1 = clean["H001"]
    assert h1.ward == "渋谷区"
    assert h1.log_area == pytest.approx(math.log(25.5))
    assert h1.rent_per_m2 == pytest.approx(120000.0 / 25.5)
    assert h1.structure == "RC"


# --------------------------------------------------------------------------- #
# 4) 列名違いの CSV を column_map で解決できる
# --------------------------------------------------------------------------- #
def test_column_map_resolves_alternate_headers(tmp_path) -> None:
    # 別名ヘッダの CSV を別 column_map で解決。
    csv = tmp_path / "alt.csv"
    csv.write_text("id,cat,name,maker,u,size,jpy,sale,stock\n"
                   "X1,穀類,米,農協,kg,2,1000,true,true\n", encoding="utf-8")
    alt_map = {
        "id": "item_id", "cat": "category", "name": "product_name", "maker": "brand",
        "u": "unit", "size": "unit_size", "jpy": "price", "sale": "is_promo", "stock": "in_stock",
    }
    src = SourceConfig(id="alt", enabled=True, type="csv", path=str(csv), column_map=alt_map)
    records = CsvFoodImporter(src).run()
    assert len(records) == 1
    assert records[0]["item_id"] == "X1"
    assert records[0]["price"] == 1000.0
    assert records[0]["is_promo"] is True


# --------------------------------------------------------------------------- #
# 5) daily.run が csv ソースを end-to-end 取り込み -> index_values 生成
# --------------------------------------------------------------------------- #
def test_daily_run_picks_up_csv_source(fresh_db, tmp_path, monkeypatch) -> None:
    from jobs import daily
    from scrapers.base import load_sources as real_load_sources

    # 基準期の食料 clean を直接 seed（csv の as_of と matched にする）。
    with fresh_db.get_session() as s:
        for sku_key, cat, up in [
            ("農協|コシヒカリ|mass", "穀類", 50.0),
            ("ja|たまご|count", "乳卵類", 25.0),
        ]:
            s.add(
                FoodClean(
                    item_id=f"base-{sku_key}", source="seed", scrape_date=BASE_DATE,
                    first_seen=BASE_DATE, last_seen=BASE_DATE, is_active=True,
                    category=cat, sku_key=sku_key, unit_price=up, is_promo=False,
                )
            )
        s.commit()

    # テスト用 sources.yaml（food に csv ソース、housing は空）。
    sources_yaml = tmp_path / "sources.yaml"
    sources_yaml.write_text(
        yaml.safe_dump(
            {
                "housing": [],
                "food": [
                    {
                        "id": "estat_food", "enabled": True, "type": "csv",
                        "path": str(FOOD_CSV), "column_map": FOOD_MAP,
                    }
                ],
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        daily, "load_sources", lambda kind: real_load_sources(kind, path=sources_yaml)
    )

    rc = daily.run(as_of=AS_OF, methodology_path=tmp_path / "m.md")
    assert rc == 0

    with fresh_db.get_session() as s:
        raw = s.exec(select(FoodRaw).where(FoodRaw.source == "estat_food")).all()
        clean = s.exec(select(FoodClean).where(FoodClean.source == "estat_food")).all()
        food_idx = s.exec(
            select(IndexValue).where(
                IndexValue.index_code == "JP-INFL-FOOD", IndexValue.date == AS_OF
            )
        ).all()
        nowcast = s.exec(
            select(IndexValue).where(
                IndexValue.index_code == "JP-INFL-NOWCAST", IndexValue.date == AS_OF
            )
        ).all()

    # csv インポートが raw/clean に到達。
    assert len(raw) == 4
    assert any(c.unit_price == pytest.approx(50.0) for c in clean)
    # index_values まで配線。matched は base と一致 -> FOOD ≈ 100。
    assert len(food_idx) == 1
    assert food_idx[0].value == pytest.approx(100.0, rel=1e-9)
    assert len(nowcast) == 1
    assert nowcast[0].coverage_pct == pytest.approx(2626.0 / 10000.0 * 100.0)
