"""住居 主系列: 回転ヘドニック + 代表バスケット予測（§6-1）。

手順:
1. 直近 rolling_window_days の active 募集で ln(rent_total) を特徴量
   (log_area, ward, age_band, walk_band, floor, structure, madori) に OLS 回帰。
2. config/baskets.yaml の代表ユニット群の賃料を予測。
3. 基準期予測値に対する比 × base_value を指数化。

構成バイアス耐性（受け入れ条件, Phase 2）: 価格一律 +5% -> 指数 +5%、
構成のみ変化 -> 指数不変（代表バスケットを固定して予測するため）。

実装方針: patsy の数式ではなく手組みの設計行列（get_dummies + drop_first）を使う。
これにより、学習データに無いカテゴリ水準は予測時に全ダミー 0 = 基準水準へ「中立化」され、
例外を出さずに済む（§6-1 の要件）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import statsmodels.api as sm
import yaml

BASKETS_PATH = Path(__file__).resolve().parent.parent / "config" / "baskets.yaml"

_NUM_COLS = ["log_area", "floor"]
_CAT_COLS = ["ward", "age_band", "walk_band", "structure", "madori"]
# これ未満なら回帰が不安定なのでカテゴリ項を落として log_area のみに退避する。
_MIN_N_FOR_CATEGORICAL = 12


@lru_cache
def _housing_config() -> dict[str, Any]:
    if not BASKETS_PATH.exists():
        return {}
    data = yaml.safe_load(BASKETS_PATH.read_text(encoding="utf-8")) or {}
    return data.get("housing") or {}


def rolling_window_days() -> int:
    return int(_housing_config().get("rolling_window_days", 28))


def representative_units() -> list[dict[str, Any]]:
    return list(_housing_config().get("representative_units") or [])


@dataclass
class HedonicModel:
    """学習済みヘドニックモデル（OLS 結果 + 設計行列の列順）。"""

    result: Any  # statsmodels RegressionResults
    columns: list[str]
    use_categorical: bool


def _ensure_log_area(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "log_area" not in out.columns:
        out["log_area"] = np.nan
    missing = out["log_area"].isna()
    if "area_m2" in out.columns and missing.any():
        area = pd.to_numeric(out.loc[missing, "area_m2"], errors="coerce")
        out.loc[missing, "log_area"] = np.log(area.where(area > 0))
    return out


def _design_matrix(
    df: pd.DataFrame, *, use_categorical: bool, columns: list[str] | None = None
) -> pd.DataFrame:
    """特徴量から設計行列を作る。columns 指定時はその列順に整列（予測時の中立化）。"""
    d = df.copy()
    for c in _NUM_COLS:
        d[c] = pd.to_numeric(d.get(c), errors="coerce")
    parts = [d[_NUM_COLS].astype(float).reset_index(drop=True)]

    if use_categorical:
        cats = d[_CAT_COLS].astype("string").fillna("NA").astype(str).reset_index(drop=True)
        dummies = pd.get_dummies(cats, columns=_CAT_COLS, drop_first=True, dtype=float)
        parts.append(dummies)

    x = pd.concat(parts, axis=1)
    x.insert(0, "const", 1.0)

    if columns is not None:
        # 学習時の列に整列。未知ダミー列は 0（基準水準へ中立化）、余剰は捨てる。
        x = x.reindex(columns=columns, fill_value=0.0)
    return x


def fit_hedonic(df: pd.DataFrame) -> HedonicModel:
    """ln(rent_total) を特徴量に OLS 回帰したモデルを返す（§6-1）。

    小標本・rank 不足・カテゴリ欠落をガードする。
    """
    d = _ensure_log_area(df)
    d = d[pd.to_numeric(d["rent_total"], errors="coerce") > 0]
    d = d[pd.to_numeric(d["log_area"], errors="coerce").notna()]
    if len(d) == 0:
        raise ValueError("hedonic fit: 有効な行がありません")

    use_categorical = len(d) >= _MIN_N_FOR_CATEGORICAL
    y = np.log(pd.to_numeric(d["rent_total"], errors="coerce").to_numpy(dtype=float))
    x = _design_matrix(d, use_categorical=use_categorical)

    # rank 不足なら特異行列でも pinv で解ける OLS を使い、例外を出さない。
    result = sm.OLS(y, x.to_numpy(dtype=float)).fit()
    return HedonicModel(result=result, columns=x.columns.tolist(), use_categorical=use_categorical)


def predict_basket(model: HedonicModel, basket: list[dict[str, Any]]) -> float:
    """代表バスケット各スペックの ln(rent) を予測し exp、ストックウェイトで加重平均する。

    学習データに無いカテゴリ水準は設計行列の中立化により例外を出さない（§6-1）。
    """
    if not basket:
        raise ValueError("predict_basket: basket が空です")

    rows = []
    weights = []
    for unit in basket:
        area = unit.get("area_m2")
        log_area = unit.get("log_area")
        if log_area is None and area:
            log_area = math.log(float(area))
        rows.append(
            {
                "log_area": log_area,
                "floor": unit.get("floor"),
                "ward": unit.get("ward"),
                "age_band": unit.get("age_band"),
                "walk_band": unit.get("walk_band"),
                "structure": unit.get("structure"),
                "madori": unit.get("madori"),
            }
        )
        weights.append(float(unit.get("weight", 1.0)))

    frame = pd.DataFrame(rows)
    x = _design_matrix(frame, use_categorical=model.use_categorical, columns=model.columns)
    ln_pred = np.asarray(model.result.predict(x.to_numpy(dtype=float)), dtype=float)
    rent_pred = np.exp(ln_pred)
    w = np.asarray(weights, dtype=float)
    return float(np.average(rent_pred, weights=w))


def _window(df: pd.DataFrame, *, end: date, window_days: int) -> pd.DataFrame:
    """end を末尾とする window_days 日の active 行を抽出する。"""
    d = df.copy()
    d["date"] = pd.to_datetime(d["date"]).dt.date
    start = end - timedelta(days=window_days - 1)
    mask = (d["date"] >= start) & (d["date"] <= end)
    if "is_active" in d.columns:
        mask &= d["is_active"].fillna(True).astype(bool)
    return d[mask]


def compute(df: pd.DataFrame, *, as_of: date, base_value: float, base_date: date) -> dict[str, Any]:
    """指定日のヘドニック住居指数値（IndexValue 相当の dict）を返す。

    base 窓・as_of 窓を df の date 列から内部抽出し、それぞれ fit→predict した
    代表賃料の比 × base_value を指数化する。
    """
    window_days = rolling_window_days()
    basket = representative_units()

    base_df = _window(df, end=base_date, window_days=window_days)
    asof_df = _window(df, end=as_of, window_days=window_days)

    base_pred = predict_basket(fit_hedonic(base_df), basket)
    asof_model = fit_hedonic(asof_df)
    asof_pred = predict_basket(asof_model, basket)

    value = base_value * (asof_pred / base_pred)
    return {
        "index_code": "JP-INFL-HOUSING",
        "date": as_of,
        "series_type": "stock_hedonic",
        "value": value,
        "base_value": base_value,
        "base_date": base_date,
        "n": int(len(asof_df)),
    }
