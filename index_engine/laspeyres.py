"""層別ラスパイレス クロスチェック（§6-1 住居 / §6-2 食料の上位集計）。

住居: ward × madori × age_band × walk_band の中央 ¥/m² を基準期固定ウェイトで加重。
主系列（ヘドニック）との乖離を監視値として記録する。
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd


def compute(
    df: pd.DataFrame,
    *,
    as_of: date,
    base_cells: dict[str, float],
    weights: dict[str, float],
    base_date: date,
) -> dict[str, Any]:
    """層別ラスパイレス指数値（IndexValue 相当 dict, series_type='crosscheck'）を返す。"""
    raise NotImplementedError("Phase 2: 層別ラスパイレスを実装する")
