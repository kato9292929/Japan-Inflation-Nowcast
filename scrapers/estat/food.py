"""e-Stat 食料 価格フェッチャー（用途A: 価格・検証アンカー, §8）。

小売物価統計調査の品目別価格を取得し、FoodRaw 形のレコード（etl.food.upsert_raw が読める
dict）にマップする。実通信なしでテストするため HTTP クライアントは注入可能。

config（SourceConfig.options）で受けるキー（実 ID は運用者が appId で特定して pin する前提）:
    stats_data_id : str   # 小売物価統計の statsDataId（TODO: 運用者が pin）
    item_class_id : str   # 品目コードの class id（既定 'cat01'）
    area_class_id : str   # 地域コードの class id（既定 'area'）
    cdArea        : str   # 地域コード（任意・API 側フィルタ）
    cdTime        : str   # 時点コード（任意）
    cdCat01       : str   # 品目コード（任意・カンマ区切り）
    category_map  : dict  # 品目コード or 品目名 -> CPI 食料中分類名
    default_unit  : str   # unit の既定（小売物価は 1 単位あたり価格のため通常 'g'/'ml'/'個' 等）
    unit_size     : float # unit_size の既定（既定 1.0）

注意（§8）: e-Stat 利用規約・出典表示・関連法の遵守は運用者責任。生データは非再配布。
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from scrapers.base import SourceConfig
from scrapers.estat.client import (
    EStatClient,
    EStatError,
    extract_class_lookup,
    extract_values,
)
from storage.db import get_settings

logger = logging.getLogger(__name__)


def parse_price_records(
    data: dict[str, Any], *, source: str, options: dict[str, Any]
) -> list[dict[str, Any]]:
    """getStatsData の JSON を FoodRaw 形レコードの list に変換する。"""
    item_cid = options.get("item_class_id", "cat01")
    category_map = options.get("category_map") or {}
    default_unit = options.get("default_unit")
    unit_size = float(options.get("unit_size", 1.0))

    lookup = extract_class_lookup(data)
    item_names = lookup.get(item_cid, {})

    records: list[dict[str, Any]] = []
    for v in extract_values(data):
        code = v.get(f"@{item_cid}")
        if code is None:
            continue
        name = item_names.get(str(code), str(code))
        # 価格（$）。数値化できない（"-" 等の欠測）行は捨てる。
        try:
            price = float(v.get("$"))
        except (TypeError, ValueError):
            continue
        # CPI 中分類: code 優先、無ければ name でマップ。無ければ name をそのまま。
        category = category_map.get(str(code)) or category_map.get(name) or name
        records.append(
            {
                "source": source,
                "item_id": str(code),
                "category": category,
                "product_name": name,
                "brand": None,
                "unit": default_unit or v.get("@unit"),
                "unit_size": unit_size,
                "price": price,
                "is_promo": False,
                "in_stock": True,
                "raw_payload": dict(v),
            }
        )
    return records


class EStatFoodFetcher:
    """estat タイプの食料アダプタ。既存スクレイパ互換の .run() を持つ。"""

    kind = "food"

    def __init__(
        self,
        config: SourceConfig,
        *,
        user_agent: str | None = None,  # estat では未使用（コンストラクタ互換）
        contact: str | None = None,
        client: httpx.Client | None = None,
        app_id: str | None = None,
    ) -> None:
        self.config = config
        self._app_id = app_id if app_id is not None else get_settings().estat_app_id
        self._client = client

    def run(self) -> list[dict[str, Any]]:
        """e-Stat から価格を取得し FoodRaw 形レコードを返す。

        appId 未設定・statsDataId 未指定・通信失敗時は安全に空を返す（全体を落とさない, §8）。
        """
        stats_data_id = self.config.options.get("stats_data_id")
        if not stats_data_id:
            logger.warning("estat source '%s': stats_data_id 未指定; skip", self.config.id)
            return []
        if not self._app_id:
            logger.warning("estat source '%s': ESTAT_APP_ID 未設定; skip", self.config.id)
            return []

        opts = self.config.options
        api_params = {
            "cdArea": opts.get("cdArea"),
            "cdTime": opts.get("cdTime"),
            "cdCat01": opts.get("cdCat01"),
        }
        estat = EStatClient(self._app_id, client=self._client)
        try:
            data = estat.get_stats_data(stats_data_id, **api_params)
        except EStatError as exc:
            logger.warning("estat source '%s' fetch failed: %s", self.config.id, exc)
            return []
        finally:
            if self._client is None:
                estat.close()

        return parse_price_records(data, source=self.config.id, options=opts)
