"""食料 ETL（§5, §6-2）。生 food -> food_clean。

責務:
- SKU 名寄せ（同一商品を時系列で追跡できる sku_key を付与）。
- 単価正規化（unit_price = price / unit_size）。
- ライフサイクル更新（first_seen / last_seen / is_active）。
- CPI 食料中分類（category）へのマップ確認。

すべて冪等（§3）。
"""

from __future__ import annotations

from datetime import date
from typing import Any


def upsert_raw(records: list[dict[str, Any]], *, scrape_date: date) -> int:
    """生レコードを food_raw に冪等 upsert し、ライフサイクルを更新する。"""
    raise NotImplementedError("Phase 3: food_raw への冪等 upsert を実装する")


def resolve_sku_key(record: dict[str, Any]) -> str:
    """商品名・ブランド・容量から名寄せ用の安定 sku_key を生成する。"""
    raise NotImplementedError("Phase 3: SKU 名寄せを実装する")


def normalize_unit_price(record: dict[str, Any]) -> float | None:
    """単価（price / unit_size）を正規化して返す。"""
    raise NotImplementedError("Phase 3: 単価正規化を実装する")


def run(*, scrape_date: date) -> int:
    """food_raw -> food_clean を冪等に再構築する。"""
    raise NotImplementedError("Phase 3: 食料 ETL パイプラインを実装する")
