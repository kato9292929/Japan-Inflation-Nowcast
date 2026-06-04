"""e-Stat（政府統計の総合窓口）フェッチャー（§8）。

- 用途A（価格・検証アンカー）: 小売物価統計の品目別価格 -> FoodRaw 形（food.py）。
- 用途B（公式ウェイト）: 2020 年基準 CPI 食料中分類ウェイト -> baskets.yaml（weights.py）。

live は運用者の環境で appId（ESTAT_APP_ID）を入れて実行する前提。実 statsDataId は
運用者が pin する。実通信なしでテスト（API レスポンスをモック）。
利用規約・出典表示・関連法の遵守は運用者責任（§8）。
"""

from scrapers.estat.food import EStatFoodFetcher

__all__ = ["EStatFoodFetcher"]
