"""住居 ETL（§5, §6-1）。生 listings -> listings_clean。

責務:
- 住所/区/駅の正規化（config/normalize/*.yaml）。
- dedup（同一 listing_id の統合）。
- ライフサイクル更新（first_seen / last_seen / is_active）。
- ヘドニック用特徴量（log_area, age_band, walk_band, rent_per_m2）。

すべて冪等（同日再実行で二重計上しない, §3）。
"""

from __future__ import annotations

from datetime import date
from typing import Any


def upsert_raw(records: list[dict[str, Any]], *, scrape_date: date) -> int:
    """生レコードを listings_raw に冪等 upsert し、ライフサイクルを更新する。

    Returns: 取り込んだ行数。
    """
    raise NotImplementedError("Phase 1: listings_raw への冪等 upsert を実装する")


def normalize_listing(record: dict[str, Any]) -> dict[str, Any]:
    """1 物件を正規化（ward/station/address、数値整形）。"""
    raise NotImplementedError("Phase 1: 物件正規化を実装する")


def build_features(record: dict[str, Any]) -> dict[str, Any]:
    """ヘドニック特徴量（log_area, age_band, walk_band, rent_per_m2）を付与する。"""
    raise NotImplementedError("Phase 1: 特徴量生成を実装する")


def run(*, scrape_date: date) -> int:
    """listings_raw -> listings_clean を冪等に再構築する。

    Returns: 生成した clean 行数。
    """
    raise NotImplementedError("Phase 1: 住居 ETL パイプラインを実装する")
