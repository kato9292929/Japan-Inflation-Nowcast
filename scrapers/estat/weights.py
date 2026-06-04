"""e-Stat 公式ウェイト取得（用途B, §6-3 / §8）。

2020 年基準 CPI の食料 中分類ウェイトを e-Stat から取得し、config/baskets.yaml の
food.categories[*].weight に書き込む一回限りのヘルパー。

重要: ハードコードした数値は置かない。必ず公式取得値を書く。実 statsDataId は運用者が
appId で特定して pin する前提（live は運用者の環境で実行）。このサンドボックスからは
api.e-stat.go.jp に出られないため、実通信なしで関数をテストする。

注意（§8）: e-Stat 利用規約・出典表示の遵守は運用者責任。
"""

from __future__ import annotations

import argparse
import logging
import re
from pathlib import Path
from typing import Any

import httpx

from scrapers.estat.client import EStatClient, extract_class_lookup, extract_values
from storage.db import get_settings

logger = logging.getLogger(__name__)

BASKETS_PATH = Path(__file__).resolve().parents[2] / "config" / "baskets.yaml"


def parse_food_weights(
    data: dict[str, Any], *, class_id: str = "cat01"
) -> dict[str, float]:
    """getStatsData の JSON から {中分類名: weight} を抽出する。

    値（$）がウェイト（10000 分比など）。名前は CLASS_INF から引く。
    """
    lookup = extract_class_lookup(data).get(class_id, {})
    weights: dict[str, float] = {}
    for v in extract_values(data):
        code = v.get(f"@{class_id}")
        if code is None:
            continue
        try:
            w = float(v.get("$"))
        except (TypeError, ValueError):
            continue
        name = lookup.get(str(code), str(code))
        weights[name] = w
    return weights


def fetch_food_weights(
    stats_data_id: str,
    *,
    app_id: str | None = None,
    client: httpx.Client | None = None,
    class_id: str = "cat01",
    **api_params: Any,
) -> dict[str, float]:
    """e-Stat から食料中分類ウェイトを取得して {名前: weight} を返す。"""
    app_id = app_id if app_id is not None else get_settings().estat_app_id
    estat = EStatClient(app_id, client=client)
    try:
        data = estat.get_stats_data(stats_data_id, **api_params)
    finally:
        if client is None:
            estat.close()
    return parse_food_weights(data, class_id=class_id)


def validate_weights(weights: dict[str, float]) -> None:
    """取得ウェイトの健全性チェック（空でない・全て正・合計が正）。"""
    if not weights:
        raise ValueError("取得ウェイトが空です")
    if any(w <= 0 for w in weights.values()):
        raise ValueError("ウェイトに 0 以下が含まれます")
    if sum(weights.values()) <= 0:
        raise ValueError("ウェイト合計が 0 以下です")


def update_food_weights(
    weights: dict[str, float], *, baskets_path: Path = BASKETS_PATH
) -> int:
    """baskets.yaml の food.categories[*].weight を取得値で書き換える（コメント保持）。

    名前一致した category 行のみ weight を更新する。Returns: 更新した行数。
    """
    validate_weights(weights)
    text = baskets_path.read_text(encoding="utf-8")
    updated = 0
    for name, w in weights.items():
        # 例: - { name: "穀類",       weight: 1 }
        pattern = re.compile(
            rf'(name:\s*"{re.escape(name)}"\s*,\s*weight:\s*)([0-9]+(?:\.[0-9]+)?)'
        )
        new_text, n = pattern.subn(rf"\g<1>{w:g}", text, count=1)
        if n:
            text = new_text
            updated += 1
        else:
            logger.warning("baskets.yaml に中分類 '%s' が見つからず未更新", name)
    baskets_path.write_text(text, encoding="utf-8")
    return updated


def main() -> int:
    """CLI: e-Stat から食料ウェイトを取得し baskets.yaml を更新（jin-fetch-weights）。"""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(
        description="e-Stat から 2020 年基準 CPI 食料中分類ウェイトを取得し baskets.yaml に書き込む"
    )
    parser.add_argument(
        "--stats-data-id", required=True, help="CPI ウェイト表の statsDataId（運用者が pin）"
    )
    parser.add_argument("--class-id", default="cat01", help="中分類の class id（既定 cat01）")
    parser.add_argument("--cd-time", default=None, help="時点コード（任意）")
    args = parser.parse_args()

    weights = fetch_food_weights(
        args.stats_data_id, class_id=args.class_id, cdTime=args.cd_time
    )
    n = update_food_weights(weights)
    logger.info("baskets.yaml の food ウェイトを %d 件更新しました", n)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
