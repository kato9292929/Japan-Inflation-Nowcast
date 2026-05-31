"""食料アダプタの参照実装（フィクスチャ検証用 / 実サイト用ではない）。

重要（§8）:
- これは **実在サイト用のアダプタではない**。下記「HTML 契約」に一致する固定
  フィクスチャ（tests/fixtures/food_example.html）を解析するための参照枠である。
- 実サイト向けアダプタは **運用者が後で** scrapers/food/<source_id>.py として
  追加する。その際、対象サイトの利用規約・robots.txt・著作権・関連法の遵守は
  運用者責任である（§8）。コード側は法的判断をしない。
- 既定では何も取得しない（config/sources.yaml の food は空, §8）。

HTML 契約（このアダプタが期待する構造）:
    各商品は ``div.item`` で表し、商品 ID を ``data-item-id`` 属性に持つ。
    各フィールドは ``.item`` 配下の以下の CSS クラスを持つ要素のテキストで与える:

        data-item-id   -> item_id      （属性, 必須）
        .category      -> category     （CPI 食料中分類）
        .product-name  -> product_name
        .brand         -> brand
        .unit          -> unit         （例 g / ml / 個 / kg / l）
        .unit-size     -> unit_size    （数値, 小数可）
        .price         -> price        （円, カンマ可）
        .is-promo      -> is_promo     （true/false 等のブール）
        .in-stock      -> in_stock     （true/false 等のブール）

    値が欠ける要素は省略してよい。SKU 名寄せ・単価正規化・ライフサイクルは
    ETL（etl/food.py）が行う。parse は抽出に徹する。
"""

from __future__ import annotations

from typing import Any

from selectolax.parser import HTMLParser

from scrapers.base import BaseScraper

_TEXT_FIELDS: dict[str, str] = {
    ".category": "category",
    ".product-name": "product_name",
    ".brand": "brand",
    ".unit": "unit",
}
_NUM_FIELDS: dict[str, str] = {
    ".unit-size": "unit_size",
    ".price": "price",
}
_BOOL_FIELDS: dict[str, tuple[str, bool]] = {
    # selector -> (key, default)
    ".is-promo": ("is_promo", False),
    ".in-stock": ("in_stock", True),
}

_TRUE_TOKENS = {"true", "1", "yes", "y", "促销", "特売", "セール", "promo"}
_FALSE_TOKENS = {"false", "0", "no", "n"}


def _node_text(node: Any, selector: str) -> str | None:
    child = node.css_first(selector)
    if child is None:
        return None
    text = child.text(strip=True)
    return text or None


def _to_number(text: str | None) -> float | None:
    if text is None:
        return None
    cleaned = text.replace(",", "").replace("¥", "").replace("円", "").strip()
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _to_bool(text: str | None, default: bool) -> bool:
    if text is None:
        return default
    token = text.strip().lower()
    if token in _TRUE_TOKENS:
        return True
    if token in _FALSE_TOKENS:
        return False
    return default


class ExampleFoodScraper(BaseScraper):
    """HTML 契約に一致するページから FoodRaw 相当の生レコードを抽出する参照アダプタ。"""

    kind = "food"

    def parse(self, html: str, *, source_path: str) -> list[dict[str, Any]]:
        """HTML 契約（モジュール docstring 参照）に従い生レコードの list を返す。

        各レコードは ``source``（=アダプタ id）と ``item_id`` を必ず持つ。
        item_id が無いノードはスキップする。
        """
        tree = HTMLParser(html)
        records: list[dict[str, Any]] = []
        for node in tree.css(".item"):
            item_id = (node.attributes or {}).get("data-item-id")
            if not item_id:
                continue

            raw_strings: dict[str, str | None] = {}
            record: dict[str, Any] = {
                "source": self.config.id,
                "item_id": item_id,
                "source_path": source_path,
            }
            for selector, key in _TEXT_FIELDS.items():
                value = _node_text(node, selector)
                record[key] = value
                raw_strings[key] = value
            for selector, key in _NUM_FIELDS.items():
                value = _node_text(node, selector)
                raw_strings[key] = value
                record[key] = _to_number(value)
            for selector, (key, default) in _BOOL_FIELDS.items():
                value = _node_text(node, selector)
                raw_strings[key] = value
                record[key] = _to_bool(value, default)

            record["raw_payload"] = raw_strings
            records.append(record)
        return records
