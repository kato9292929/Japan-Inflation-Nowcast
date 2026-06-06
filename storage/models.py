"""SQLModel テーブル定義（§5 データモデル）。

非交渉制約（§0）の反映:
- 生データ（``listings_raw`` / ``food_raw``）は内部保存のみ。公開 API では派生集計だけを返す。
- すべての指数値は ``base_date`` と ``methodology_version`` を必ず持つ（§6-4）。
- 合成値には ``coverage_pct`` を必ず付ける（§0「CPI バスケットの約 X% をカバー」）。

識別子・カラム名は英語（§3）。docstring は日本語可。
"""

from __future__ import annotations

from datetime import UTC, datetime
from datetime import date as Date  # 別名: フィールド名 `date` と型名の衝突を避ける
from typing import Any

from sqlalchemy import Column, Index, UniqueConstraint
from sqlalchemy.types import JSON
from sqlmodel import Field, SQLModel


# --------------------------------------------------------------------------- #
# 住居 生データ / クリーン（§5, §6-1）
# --------------------------------------------------------------------------- #
class ListingRaw(SQLModel, table=True):
    """住居の生取得。再配布禁止（§8）。ライフサイクルを first/last_seen で追跡。"""

    __tablename__ = "listings_raw"

    id: int | None = Field(default=None, primary_key=True)
    listing_id: str = Field(index=True, description="ソース内の物件ID")
    source: str = Field(index=True, description="アダプタ id（config/sources.yaml）")
    scrape_date: Date = Field(index=True)
    first_seen: Date
    last_seen: Date
    is_active: bool = Field(default=True, index=True)

    ward: str | None = None
    address_norm: str | None = None
    station: str | None = None
    walk_min: int | None = None
    rent_total: float | None = None
    mgmt_fee: float | None = None
    area_m2: float | None = None
    madori: str | None = None
    build_year: int | None = None
    floor: int | None = None
    structure: str | None = None
    deposit: float | None = None
    key_money: float | None = None

    raw_payload: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))


class ListingClean(SQLModel, table=True):
    """住居の正規化・dedup・特徴量済み（§5）。指数エンジンの入力。"""

    __tablename__ = "listings_clean"

    id: int | None = Field(default=None, primary_key=True)
    listing_id: str = Field(index=True)
    source: str = Field(index=True)
    scrape_date: Date = Field(index=True)
    first_seen: Date
    last_seen: Date
    is_active: bool = Field(default=True, index=True)

    ward: str | None = Field(default=None, index=True)
    address_norm: str | None = None
    station: str | None = None
    walk_min: int | None = None
    rent_total: float | None = None
    mgmt_fee: float | None = None
    area_m2: float | None = None
    madori: str | None = None
    build_year: int | None = None
    floor: int | None = None
    structure: str | None = None
    deposit: float | None = None
    key_money: float | None = None

    # 派生特徴量（§6-1 ヘドニック用）
    log_area: float | None = None
    age_band: int | None = None
    walk_band: int | None = None
    rent_per_m2: float | None = None


# --------------------------------------------------------------------------- #
# 食料 生データ / クリーン（§5, §6-2）
# --------------------------------------------------------------------------- #
class FoodRaw(SQLModel, table=True):
    """食料の生取得（日次パネル, §5, §6-2）。再配布禁止（§8）。

    natural key は (source, item_id, scrape_date)。SKU ごとに 1 日 1 行を保持し、
    任意の過去日のスナップショットを復元できる（固定基準日に対する複数日 Jevons の前提）。
    ライフサイクル列（first_seen/last_seen/is_active）は SKU 単位の真実で、同一 SKU の
    全行に冗長コピーされる（etl.food.upsert_raw が整合させる）。
    """

    __tablename__ = "food_raw"
    __table_args__ = (
        UniqueConstraint("source", "item_id", "scrape_date", name="uq_food_raw_sku_date"),
        Index("ix_food_raw_source_date", "source", "scrape_date"),
    )

    id: int | None = Field(default=None, primary_key=True)
    item_id: str = Field(index=True, description="ソース内の商品ID（SKU）")
    source: str = Field(index=True)
    scrape_date: Date = Field(index=True)
    first_seen: Date
    last_seen: Date
    is_active: bool = Field(default=True, index=True)

    category: str | None = Field(default=None, description="CPI 食料中分類")
    product_name: str | None = None
    brand: str | None = None
    unit: str | None = None
    unit_size: float | None = None
    price: float | None = None
    is_promo: bool = Field(default=False)
    in_stock: bool = Field(default=True)

    raw_payload: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))


class FoodClean(SQLModel, table=True):
    """食料の名寄せ・単価正規化・ライフサイクル済み（日次パネル, §5）。指数エンジンの入力。

    natural key は (source, item_id, scrape_date)。各 scrape_date 行を独立に保持し、
    _snapshot(on=date) が日付ごとに正しい SKU セットを返せるようにする。
    """

    __tablename__ = "food_clean"
    __table_args__ = (
        UniqueConstraint("source", "item_id", "scrape_date", name="uq_food_clean_sku_date"),
        Index("ix_food_clean_source_date", "source", "scrape_date"),
    )

    id: int | None = Field(default=None, primary_key=True)
    item_id: str = Field(index=True)
    source: str = Field(index=True)
    scrape_date: Date = Field(index=True)
    first_seen: Date
    last_seen: Date
    is_active: bool = Field(default=True, index=True)

    category: str | None = Field(default=None, index=True)
    product_name: str | None = None
    brand: str | None = None
    unit: str | None = None
    unit_size: float | None = None
    price: float | None = None
    is_promo: bool = Field(default=False)
    in_stock: bool = Field(default=True)

    # 派生（§6-2 単価正規化）
    sku_key: str | None = Field(default=None, index=True, description="名寄せ後の SKU 連続キー")
    unit_price: float | None = Field(default=None, description="price / unit_size")


# --------------------------------------------------------------------------- #
# 指数値（§5 index_values）
# --------------------------------------------------------------------------- #
class IndexValue(SQLModel, table=True):
    """全指数の出力行（§5）。

    すべての値に base_date と methodology_version を紐付ける（§6-4）。
    合成値は series_type='composite_partial' と coverage_pct を必ず持つ（§0, §6-3）。
    """

    __tablename__ = "index_values"

    id: int | None = Field(default=None, primary_key=True)
    index_code: str = Field(index=True, description="JP-INFL-NOWCAST / -FOOD / -HOUSING など")
    date: Date = Field(index=True)
    freq: str = Field(default="D", description="D / W / M")

    value: float
    base_value: float | None = None
    base_date: Date

    yoy_pct: float | None = None
    mom_pct: float | None = None
    wow_pct: float | None = None

    n: int | None = Field(default=None, description="観測件数")
    n_new: int | None = Field(default=None, description="新規件数")

    series_type: str = Field(
        default="component",
        description="component / composite_partial / crosscheck / flow など",
    )
    coverage_pct: float | None = Field(
        default=None, description="CPI バスケットのカバー率（合成で必須, §0）"
    )
    promo_mode: str | None = Field(default=None, description="incl_promo / excl_promo（§6-2）")
    components: list[dict[str, Any]] | None = Field(default=None, sa_column=Column(JSON))
    smoothing_window_days: int | None = None
    methodology_version: str = Field(index=True)

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


# --------------------------------------------------------------------------- #
# 方法論バージョン（§5 methodology_versions）
# --------------------------------------------------------------------------- #
class MethodologyVersion(SQLModel, table=True):
    """方法論のバージョン台帳（§5）。リベース・算式変更で行を起こす。"""

    __tablename__ = "methodology_versions"

    version: str = Field(primary_key=True)
    effective_date: Date
    formula_notes: str | None = None
    weights_source: str | None = None
    changelog: str | None = None


__all__ = [
    "ListingRaw",
    "ListingClean",
    "FoodRaw",
    "FoodClean",
    "IndexValue",
    "MethodologyVersion",
]
