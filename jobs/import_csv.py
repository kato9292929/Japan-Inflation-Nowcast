"""ローカル CSV を指定日付で取り込む CLI（jin-import-csv, §8）。

開発・バックフィル用。ライフバスケット形式の CSV を任意の scrape_date で food_raw/
food_clean（日次パネル）に取り込む。実通信なし（ローカルファイル）。

使い方:
    jin-import-csv data/life_basket_20260604.csv --date 2026-06-04
    jin-import-csv data/life_basket_20260605.csv --date 2026-06-05 --kind food

法務（§8）: CSV の利用規約・著作権・関連法の遵守は運用者責任。生データは非再配布。
"""

from __future__ import annotations

import argparse
import logging
from datetime import date

from etl import food as etl_food
from etl import housing as etl_housing
from scrapers.base import SourceConfig
from scrapers.food.csv_import import CsvFoodImporter
from scrapers.housing.csv_import import CsvHousingImporter
from storage.db import init_db

logger = logging.getLogger("jobs.import_csv")

# ライフバスケット CSV の標準列マッピング（CSV 列名 -> raw フィールド名）。
FOOD_COLUMN_MAP = {
    "商品ID": "item_id",
    "分類": "category",
    "品名": "product_name",
    "ブランド": "brand",
    "単位": "unit",
    "内容量": "unit_size",
    "価格": "price",
    "特売": "is_promo",
}
HOUSING_COLUMN_MAP = {
    "物件ID": "listing_id",
    "区": "ward",
    "住所": "address_norm",
    "駅": "station",
    "徒歩分": "walk_min",
    "家賃": "rent_total",
    "管理費": "mgmt_fee",
    "面積": "area_m2",
    "間取り": "madori",
    "築年": "build_year",
    "階": "floor",
    "構造": "structure",
    "敷金": "deposit",
    "礼金": "key_money",
}


def import_csv(
    path: str, *, scrape_date: date, kind: str = "food", source_id: str = "csv_import"
) -> int:
    """CSV を指定日付で取り込み、clean まで再構築する。Returns: 取り込み行数。"""
    init_db()  # 新規 DB でもテーブルを保証（冪等）
    if kind == "food":
        cfg = SourceConfig(
            id=source_id, enabled=True, type="csv", path=path, column_map=FOOD_COLUMN_MAP
        )
        records = CsvFoodImporter(cfg).run()
        n = etl_food.upsert_raw(records, scrape_date=scrape_date)
        etl_food.run(scrape_date=scrape_date)
    elif kind == "housing":
        cfg = SourceConfig(
            id=source_id, enabled=True, type="csv", path=path, column_map=HOUSING_COLUMN_MAP
        )
        records = CsvHousingImporter(cfg).run()
        n = etl_housing.upsert_raw(records, scrape_date=scrape_date)
        etl_housing.run(scrape_date=scrape_date)
    else:
        raise ValueError(f"unknown kind: {kind}")
    logger.info("imported %d %s records for %s from %s", n, kind, scrape_date, path)
    return n


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="ローカル CSV を指定日付で取り込む（日次パネル）")
    parser.add_argument("path", help="CSV パス")
    parser.add_argument("--date", required=True, type=date.fromisoformat, help="scrape_date (ISO)")
    parser.add_argument("--kind", default="food", choices=["food", "housing"])
    parser.add_argument("--source-id", default="csv_import", help="source 識別子")
    args = parser.parse_args()
    import_csv(args.path, scrape_date=args.date, kind=args.kind, source_id=args.source_id)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
