"""住居ソースアダプタ（プラグイン）。

対象サイトは運用者が config/sources.yaml に記入し、対応するアダプタをここに置く
（例: scrapers/housing/<source_id>.py）。各ファイル冒頭に §8 の遵守注意を明記すること。
既定では何も取得しない（sources.yaml の housing が空）。

``example.py`` の ``ExampleHousingScraper`` は **実サイト用ではなく**、HTML 契約に
一致する固定フィクスチャを解析するための参照実装。実サイト向けは運用者が追加する。
"""

from scrapers.housing.example import ExampleHousingScraper

__all__ = ["ExampleHousingScraper"]

