"""平滑化・変化率・出力整形（§6-4）。

- 平滑化 7 日 / 28 日（トレーリング）。
- YoY / MoM / WoW（データ不足は None）。
- n（観測件数）・件数を併記。
- すべての値に base_date / methodology_version を紐付ける。
- 主系列（hedonic）とクロスチェック（laspeyres）の乖離を divergence 監視値として載せる。
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import numpy as np
import pandas as pd

# 変化率の参照ラグ（日）。
_LAGS = {"yoy_pct": 365, "mom_pct": 30, "wow_pct": 7}


def _as_datetime_series(series: pd.Series) -> pd.Series:
    """index を DatetimeIndex に整え、昇順ソートした Series を返す。"""
    s = series.copy()
    s.index = pd.to_datetime(s.index)
    return s.sort_index()


def smooth(series: pd.Series, *, window_days: int) -> pd.Series:
    """指定窓（7 / 28 日）のトレーリング移動平均で平滑化する。"""
    s = _as_datetime_series(series)
    return s.rolling(window=f"{window_days}D", min_periods=1).mean()


def change_rates(series: pd.Series) -> dict[str, float | None]:
    """最新値に対する YoY / MoM / WoW（%）を返す。データ不足は None。"""
    s = _as_datetime_series(series).dropna()
    out: dict[str, float | None] = {"yoy_pct": None, "mom_pct": None, "wow_pct": None}
    if len(s) == 0:
        return out

    latest_date = s.index.max()
    latest_at = s.loc[latest_date]
    latest = float(latest_at) if np.ndim(latest_at) == 0 else float(latest_at.iloc[-1])
    first_date = s.index.min()

    for key, lag in _LAGS.items():
        target = latest_date - timedelta(days=lag)
        if target < first_date:
            continue  # 参照点が履歴より前 -> None
        prior = s.asof(target)
        if prior is None or pd.isna(prior) or prior == 0:
            continue
        out[key] = (latest / float(prior) - 1.0) * 100.0
    return out


def finalize(
    value: dict[str, Any],
    *,
    methodology_version: str,
    crosscheck_value: float | None = None,
) -> dict[str, Any]:
    """IndexValue 相当 dict を出力形に整形し、methodology_version を紐付ける。

    crosscheck_value（通常 laspeyres の value）を渡すと主系列との乖離 divergence_pct
    を監視値として載せる（§6-1）。series_type はそのまま保持する。
    """
    out = dict(value)
    out["methodology_version"] = methodology_version
    out.setdefault("freq", "D")

    main = out.get("value")
    if crosscheck_value not in (None, 0) and main is not None and not pd.isna(main):
        out["divergence_pct"] = (float(main) / float(crosscheck_value) - 1.0) * 100.0
    else:
        out["divergence_pct"] = None
    return out
