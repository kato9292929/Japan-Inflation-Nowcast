"""住居アダプタの参照実装（フィクスチャ検証用 / 実サイト用ではない）。

重要（§8）:
- これは **実在サイト用のアダプタではない**。下記「HTML 契約」に一致する固定
  フィクスチャ（tests/fixtures/housing_example.html）を解析するための参照枠である。
- 実サイト向けアダプタは **運用者が後で** scrapers/housing/<source_id>.py として
  追加する。その際、対象サイトの利用規約・robots.txt・著作権・関連法の遵守は
  運用者責任である（§8）。コード側は法的判断をしない。
- 既定では何も取得しない（config/sources.yaml の housing は空, §8）。

HTML 契約（このアダプタが期待する構造）:
    各物件は ``div.listing`` で表し、物件 ID を ``data-listing-id`` 属性に持つ。
    各フィールドは ``.listing`` 配下の以下の CSS クラスを持つ要素のテキストで与える:

        data-listing-id   -> listing_id   （属性, 必須）
        .ward             -> ward
        .address          -> address       （ETL で address_norm に正規化）
        .station          -> station
        .walk-min         -> walk_min      （整数, 分）
        .rent-total       -> rent_total    （円, カンマ可）
        .mgmt-fee         -> mgmt_fee       （円, カンマ可）
        .area-m2          -> area_m2        （m^2, 小数可）
        .madori           -> madori        （間取り, 例 1K / 1LDK）
        .build-year       -> build_year    （西暦, 整数）
        .floor            -> floor          （階, 整数）
        .structure        -> structure     （構造, 例 RC / SRC / 木造）
        .deposit          -> deposit        （敷金, 円）
        .key-money        -> key_money      （礼金, 円）

    値が欠ける要素は省略してよい（None になる）。数値の最終整形・カテゴリ正規化・
    住所正規化・異常値処理は ETL（etl/housing.py）が行う。parse は抽出に徹する。
"""

from __future__ import annotations

from typing import Any

from selectolax.parser import HTMLParser

from scrapers.base import BaseScraper

# CSS クラス -> 出力キー（テキスト抽出するフィールド）。
_TEXT_FIELDS: dict[str, str] = {
    ".ward": "ward",
    ".address": "address",
    ".station": "station",
    ".madori": "madori",
    ".structure": "structure",
}
# 数値として抽出するフィールド（最終整形は ETL）。
_NUM_FIELDS: dict[str, str] = {
    ".walk-min": "walk_min",
    ".rent-total": "rent_total",
    ".mgmt-fee": "mgmt_fee",
    ".area-m2": "area_m2",
    ".build-year": "build_year",
    ".floor": "floor",
    ".deposit": "deposit",
    ".key-money": "key_money",
}


def _node_text(node: Any, selector: str) -> str | None:
    """セレクタに一致する最初の子要素のテキスト（無ければ None）。"""
    child = node.css_first(selector)
    if child is None:
        return None
    text = child.text(strip=True)
    return text or None


def _to_number(text: str | None) -> float | None:
    """カンマ・空白・円記号を除いて float 化（不正なら None）。"""
    if text is None:
        return None
    cleaned = text.replace(",", "").replace("¥", "").replace("円", "").strip()
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


class ExampleHousingScraper(BaseScraper):
    """HTML 契約に一致するページから ListingRaw 相当の生レコードを抽出する参照アダプタ。"""

    kind = "housing"

    def parse(self, html: str, *, source_path: str) -> list[dict[str, Any]]:
        """HTML 契約（モジュール docstring 参照）に従い生レコードの list を返す。

        各レコードは ``source``（=アダプタ id）と ``listing_id`` を必ず持つ。
        listing_id が無いノードはスキップする。
        """
        tree = HTMLParser(html)
        records: list[dict[str, Any]] = []
        for node in tree.css(".listing"):
            listing_id = (node.attributes or {}).get("data-listing-id")
            if not listing_id:
                # 物件 ID が無いノードは識別できないので捨てる。
                continue

            raw_strings: dict[str, str | None] = {}
            record: dict[str, Any] = {
                "source": self.config.id,
                "listing_id": listing_id,
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

            record["raw_payload"] = raw_strings
            records.append(record)
        return records
