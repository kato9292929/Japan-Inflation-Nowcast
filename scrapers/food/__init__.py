"""食料ソースアダプタ（プラグイン）。

対象サイトは運用者が config/sources.yaml に記入し、対応するアダプタをここに置く
（例: scrapers/food/<source_id>.py）。各ファイル冒頭に §8 の遵守注意を明記すること。
既定では何も取得しない（sources.yaml の food が空）。

``example.py`` の ``ExampleFoodScraper`` は **実サイト用ではなく**、HTML 契約に
一致する固定フィクスチャを解析するための参照実装。実サイト向けは運用者が追加する。
"""

from scrapers.food.example import ExampleFoodScraper

__all__ = ["ExampleFoodScraper"]

