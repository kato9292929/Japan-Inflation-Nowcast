"""住居 CSV インポータ（公式統計 / 手動パネル, §8）。

config/sources.yaml の housing に type: csv エントリを置き、path と column_map（CSV 列名 ->
raw フィールド名）を記入すると、CSV を ListingRaw 互換の dict レコードに変換する。
HTTP・robots は使わない。法令遵守・生データ非再配布は運用者責任（§8）。

出力レコードのキー（ListingRaw）:
    listing_id, ward, address_norm, station, walk_min, rent_total, mgmt_fee, area_m2,
    madori, build_year, floor, structure, deposit, key_money
    （source は config.id、scrape_date は upsert 側で付与）

注意: etl.housing.normalize_listing は 'address' または 'address_norm' から address_norm を
作るため、column_map は CSV の住所列を 'address_norm' に写像してよい。
"""

from __future__ import annotations

from scrapers.csv_base import CsvImporter


class CsvHousingImporter(CsvImporter):
    """住居パネル/公式統計 CSV → ListingRaw 互換レコード。"""

    kind = "housing"
    id_field = "listing_id"
    str_fields = ("listing_id", "ward", "address_norm", "station", "madori", "structure")
    float_fields = ("rent_total", "mgmt_fee", "area_m2", "deposit", "key_money")
    int_fields = ("walk_min", "build_year", "floor")
    bool_fields = ()
