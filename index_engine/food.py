"""食料指数: Jevons 基礎集計 + 上位ラスパイレス + 特売処理（§6-2）。

- 基礎集計（elementary）= 同一 SKU の価格相対（当日 price / 基準期 price）の幾何平均
  （Jevons）。中分類ごとに算出。
- 上位集計 = 中分類を CPI 食料ウェイトでラスパイレス加重。
- 特売 = incl_promo / excl_promo の 2 系列（基調は excl）。
- SKU 入れ替わり = 消失/新規をチェーン接続で連続化。

構成バイアス耐性（受け入れ, Phase 4）: 同一 SKU +5% -> 指数 +5%、
SKU ミックスのみ変化 -> 不変、特売除外で系列が変わる。
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd


def jevons_elementary(df: pd.DataFrame, *, base_prices: dict[str, float]) -> dict[str, float]:
    """中分類ごとに同一 SKU 価格相対の幾何平均（Jevons）を返す（§6-2）。"""
    raise NotImplementedError("Phase 4: Jevons 基礎集計を実装する")


def aggregate_laspeyres(elementary: dict[str, float], weights: dict[str, float]) -> float:
    """中分類指数を CPI ウェイトでラスパイレス加重して上位集計する（§6-2）。"""
    raise NotImplementedError("Phase 4: 上位ラスパイレス集計を実装する")


def compute(
    df: pd.DataFrame,
    *,
    as_of: date,
    base_prices: dict[str, float],
    weights: dict[str, float],
    base_date: date,
    promo_mode: str = "excl_promo",
) -> dict[str, Any]:
    """食料指数値（IndexValue 相当 dict）を返す。promo_mode で incl/excl 切替（§6-2）。"""
    raise NotImplementedError("Phase 4: 食料指数の計算を実装する")
