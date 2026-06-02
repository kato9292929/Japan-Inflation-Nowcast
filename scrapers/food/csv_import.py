"""食料 CSV インポータ（公式統計 / 手動パネル, §8）。

config/sources.yaml の food に type: csv エントリを置き、path と column_map（CSV 列名 ->
raw フィールド名）を記入すると、CSV を FoodRaw 互換の dict レコードに変換する。
HTTP・robots は使わない。法令遵守・生データ非再配布は運用者責任（§8）。

出力レコードのキー（FoodRaw）:
    item_id, category, product_name, brand, unit, unit_size, price, is_promo, in_stock
    （source は config.id、scrape_date は upsert 側で付与）
"""

from __future__ import annotations

from scrapers.csv_base import CsvImporter


class CsvFoodImporter(CsvImporter):
    """食料パネル/公式統計 CSV → FoodRaw 互換レコード。"""

    kind = "food"
    id_field = "item_id"
    str_fields = ("item_id", "category", "product_name", "brand", "unit")
    float_fields = ("unit_size", "price")
    int_fields = ()
    bool_fields = ("is_promo", "in_stock")
