"""住居 主系列: 回転ヘドニック + 代表バスケット予測（§6-1）。

手順:
1. 直近 28 日ローリング窓の active 募集で ln(rent_total) を特徴量
   (log_area, ward, age_band, walk_band, floor, structure, madori) に OLS 回帰。
2. config/baskets.yaml の代表ユニット群の賃料を予測。
3. 基準期予測値に対する比 × 100 を指数化。

構成バイアス耐性（受け入れ条件, Phase 2）: 価格一律 +5% -> 指数 +5%、
構成のみ変化 -> 指数不変。
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd


def fit_hedonic(df: pd.DataFrame) -> Any:
    """ln(rent_total) を特徴量に OLS 回帰したモデルを返す（§6-1）。"""
    raise NotImplementedError("Phase 2: ヘドニック OLS を実装する")


def predict_basket(model: Any, basket: list[dict[str, Any]]) -> float:
    """代表バスケットの加重予測賃料を返す（§6-1）。"""
    raise NotImplementedError("Phase 2: 代表バスケット予測を実装する")


def compute(df: pd.DataFrame, *, as_of: date, base_value: float, base_date: date) -> dict[str, Any]:
    """指定日のヘドニック住居指数値（IndexValue 相当の dict）を返す。"""
    raise NotImplementedError("Phase 2: ヘドニック指数の計算を実装する")
