"""住居 新規フロー系列（§6-1）。

新規掲載（first_seen == as_of）の中央 ¥/m²（層別補正のみ）。先行シグナル。
series_type='flow'。
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd


def compute(df: pd.DataFrame, *, as_of: date, base_value: float, base_date: date) -> dict[str, Any]:
    """新規フロー指数値（IndexValue 相当 dict, series_type='flow'）を返す。"""
    raise NotImplementedError("Phase 2: 新規フロー系列を実装する")
