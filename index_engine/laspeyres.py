"""層別ラスパイレス クロスチェック（§6-1 住居）。

ward × madori × age_band × walk_band で層化し、各層の中央 ¥/m²（rent_per_m2）を算出。
基準期の固定ストックウェイト（層別件数シェア）で価格相対を加重し base_value で指数化する。
固定ウェイトのため構成変化に頑健（composition invariant）。主系列（ヘドニック）との
乖離は aggregate.finalize で divergence 監視値として記録する。
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pandas as pd

_STRATA_COLS = ["ward", "madori", "age_band", "walk_band"]


def cell_key(row: dict[str, Any]) -> str:
    """層キー（ward|madori|age_band|walk_band）。"""
    return "|".join(str(row.get(c)) for c in _STRATA_COLS)


def _window(df: pd.DataFrame, *, end: date, window_days: int) -> pd.DataFrame:
    d = df.copy()
    d["date"] = pd.to_datetime(d["date"]).dt.date
    start = end - timedelta(days=window_days - 1)
    mask = (d["date"] >= start) & (d["date"] <= end)
    if "is_active" in d.columns:
        mask &= d["is_active"].fillna(True).astype(bool)
    return d[mask]


def _rent_per_m2(df: pd.DataFrame) -> pd.Series:
    if "rent_per_m2" in df.columns and df["rent_per_m2"].notna().any():
        rpm = pd.to_numeric(df["rent_per_m2"], errors="coerce")
    else:
        rent = pd.to_numeric(df.get("rent_total"), errors="coerce")
        area = pd.to_numeric(df.get("area_m2"), errors="coerce")
        rpm = rent / area.where(area > 0)
    return rpm


def stratify(df: pd.DataFrame) -> tuple[dict[str, float], dict[str, float]]:
    """層別の中央 rent_per_m2 と件数ウェイトを返す（基準期ウェイト構築に使う）。

    Returns: (medians[cell] -> 中央 ¥/m², weights[cell] -> 件数)。
    """
    d = df.copy()
    d["_rpm"] = _rent_per_m2(d)
    d = d[d["_rpm"].notna()]
    for c in _STRATA_COLS:
        d[c] = d[c].astype("string").fillna("NA").astype(str)
    d["_cell"] = d[_STRATA_COLS].agg("|".join, axis=1)

    medians: dict[str, float] = {}
    weights: dict[str, float] = {}
    for cell, grp in d.groupby("_cell"):
        medians[cell] = float(grp["_rpm"].median())
        weights[cell] = float(len(grp))
    return medians, weights


def compute(
    df: pd.DataFrame,
    *,
    as_of: date,
    base_cells: dict[str, float],
    weights: dict[str, float],
    base_date: date,
    base_value: float = 100.0,
    window_days: int = 28,
) -> dict[str, Any]:
    """層別ラスパイレス指数値（IndexValue 相当 dict, series_type='stock_laspeyres'）を返す。

    base_cells / weights は基準期の固定値（stratify で構築）。as_of 窓の各層中央 ¥/m² を
    基準層中央で割った価格相対を、基準期固定ウェイトで加重平均し base_value 倍する。
    """
    asof_df = _window(df, end=as_of, window_days=window_days)
    asof_medians, _ = stratify(asof_df)

    num = 0.0
    den = 0.0
    matched = 0
    for cell, base_rpm in base_cells.items():
        if base_rpm in (None, 0) or cell not in asof_medians:
            continue
        w = float(weights.get(cell, 0.0))
        if w <= 0:
            continue
        relative = asof_medians[cell] / base_rpm
        num += w * relative
        den += w
        matched += 1

    value = base_value * (num / den) if den > 0 else float("nan")
    return {
        "index_code": "JP-INFL-HOUSING",
        "date": as_of,
        "series_type": "stock_laspeyres",
        "value": value,
        "base_value": base_value,
        "base_date": base_date,
        "n": int(len(asof_df)),
        "n_cells": matched,
    }
