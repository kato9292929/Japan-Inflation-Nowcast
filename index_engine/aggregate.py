"""平滑化・変化率・出力整形（§6-4）。

- 平滑化 7 日 / 28 日。
- YoY / MoM / WoW。
- n（観測件数）・信頼区間/件数を併記。
- すべての値に base_date / methodology_version を紐付ける。
"""

from __future__ import annotations

from typing import Any

import pandas as pd


def smooth(series: pd.Series, *, window_days: int) -> pd.Series:
    """指定窓（7 / 28 日）の移動平均で平滑化する。"""
    raise NotImplementedError("Phase 2: 平滑化を実装する")


def change_rates(series: pd.Series) -> dict[str, float | None]:
    """YoY / MoM / WoW（%）を返す。"""
    raise NotImplementedError("Phase 2: 変化率の計算を実装する")


def finalize(value: dict[str, Any], *, methodology_version: str) -> dict[str, Any]:
    """IndexValue 相当 dict を出力形に整形し、methodology_version を紐付ける。"""
    raise NotImplementedError("Phase 2: 出力整形を実装する")
