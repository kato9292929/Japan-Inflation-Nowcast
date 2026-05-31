"""住居 新規フロー系列（§6-1）。

新規掲載（first_seen == as_of）のみの中央 ¥/m²（rent_per_m2 = 面積による層別/サイズ補正）
を指数化する先行シグナル。series_type='flow'、n_new を併記。

既存掲載（first_seen != as_of）には影響されない（新規のみを母集団とする）。
"""

from __future__ import annotations

import math
from datetime import date
from typing import Any

import pandas as pd


def _rent_per_m2(df: pd.DataFrame) -> pd.Series:
    if "rent_per_m2" in df.columns and df["rent_per_m2"].notna().any():
        return pd.to_numeric(df["rent_per_m2"], errors="coerce")
    rent = pd.to_numeric(df.get("rent_total"), errors="coerce")
    area = pd.to_numeric(df.get("area_m2"), errors="coerce")
    return rent / area.where(area > 0)


def _new_median_rpm(df: pd.DataFrame, *, on: date) -> tuple[float, int]:
    """first_seen == on の新規掲載の中央 ¥/m² と件数を返す。"""
    d = df.copy()
    d["first_seen"] = pd.to_datetime(d["first_seen"]).dt.date
    new = d[d["first_seen"] == on].copy()
    new["_rpm"] = _rent_per_m2(new)
    new = new[new["_rpm"].notna()]
    if len(new) == 0:
        return float("nan"), 0
    return float(new["_rpm"].median()), int(len(new))


def compute(df: pd.DataFrame, *, as_of: date, base_value: float, base_date: date) -> dict[str, Any]:
    """新規フロー指数値（IndexValue 相当 dict, series_type='flow'）を返す。"""
    base_rpm, _ = _new_median_rpm(df, on=base_date)
    asof_rpm, n_new = _new_median_rpm(df, on=as_of)

    valid_base = not math.isnan(base_rpm) and base_rpm != 0
    value = base_value * (asof_rpm / base_rpm) if valid_base else float("nan")
    return {
        "index_code": "JP-INFL-HOUSING",
        "date": as_of,
        "series_type": "flow",
        "value": value,
        "base_value": base_value,
        "base_date": base_date,
        "n_new": n_new,
        "n": n_new,
    }
