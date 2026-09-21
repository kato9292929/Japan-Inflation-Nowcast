"""食料指数: Jevons 基礎集計 + 上位ラスパイレス + 特売処理（§6-2）。

- 基礎集計（elementary）= 同一 sku_key の価格相対（当期 unit_price / 基準期 unit_price）の
  幾何平均（Jevons）。中分類（category）ごとに算出。
- 上位集計 = 中分類を CPI 食料ウェイト（config/baskets.yaml）でラスパイレス加重。
- 特売 = incl_promo / excl_promo の 2 系列（基調は excl）。
- SKU 入れ替わり = 両期に揃う matched-SKU だけで相対を取り、消失/新規はチェーンで連続化。

構成バイアス耐性（受け入れ, Phase 4）: 同一 SKU +5% -> 指数 +5%、
SKU ミックスのみ変化 -> 不変、特売除外で系列が変わる。生平均は使わない。

カテゴリ脱落（§6-2 補遺）: ある日に matched SKU が 1 件も無い中分類が出ると、
aggregate_laspeyres はその中分類を除いてウェイトを再正規化する。これは「欠測カテゴリは
観測カテゴリの加重平均どおりに動いた」と置く平均代入と数学的に同値であり、単一日の集計
としては標準的だが、前日は観測・当日は代入という並びになると価格が動いていなくても指数が
跳ねる。魚介類・肉類のように 10 分類中 2 つが丸ごと落ちると、この跳ねは数 pt に達する。

そこで既定を carry_forward（直近で観測できた日の相対を持ち越す）とし、基準日より後に
一度も観測されていない中分類だけ従来どおり平均代入にフォールバックする。どの中分類を
どの日から持ち越したか、観測できていないウェイトが全体の何割かは components と
imputed_weight_share に必ず載せる（§0 透明性）。
"""

from __future__ import annotations

from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

BASKETS_PATH = Path(__file__).resolve().parent.parent / "config" / "baskets.yaml"


@lru_cache
def _food_config() -> dict[str, Any]:
    if not BASKETS_PATH.exists():
        return {}
    data = yaml.safe_load(BASKETS_PATH.read_text(encoding="utf-8")) or {}
    return data.get("food") or {}


def category_weights() -> dict[str, float]:
    """config/baskets.yaml の food.categories から category -> weight を読む。"""
    cats = _food_config().get("categories") or []
    return {c["name"]: float(c.get("weight", 1.0)) for c in cats}


def default_promo_mode() -> str:
    return str(_food_config().get("default_promo_mode", "excl_promo"))


# --------------------------------------------------------------------------- #
# 1) Jevons 基礎集計
# --------------------------------------------------------------------------- #
def jevons_elementary(
    df: pd.DataFrame,
    *,
    base_prices: dict[str, float],
    return_counts: bool = False,
) -> dict[str, float] | tuple[dict[str, float], dict[str, int]]:
    """中分類ごとに同一 sku_key 価格相対の幾何平均（Jevons）を返す（§6-2）。

    - base_prices: sku_key -> 基準期 unit_price。
    - 両期に揃う matched-SKU だけで相対を取る（片側のみの SKU は除外）。
    - unit_price が None/0/負は除外。
    - return_counts=True なら (elementary, counts[category->採用SKU数]) を返す。
    """
    elementary: dict[str, float] = {}
    counts: dict[str, int] = {}

    if len(df) == 0:
        return (elementary, counts) if return_counts else elementary

    d = df.copy()
    d["unit_price"] = pd.to_numeric(d["unit_price"], errors="coerce")
    d = d[d["unit_price"] > 0]

    for category, grp in d.groupby("category"):
        relatives: list[float] = []
        for _, row in grp.iterrows():
            sku = row["sku_key"]
            base_price = base_prices.get(sku)
            if base_price is None or base_price <= 0:
                continue  # 片側のみ -> matched でないので除外（チェーンで連続化）
            relatives.append(float(row["unit_price"]) / float(base_price))
        if relatives:
            # 幾何平均（Jevons）。生平均ではない。
            elementary[str(category)] = float(np.exp(np.mean(np.log(relatives))))
            counts[str(category)] = len(relatives)

    return (elementary, counts) if return_counts else elementary


# --------------------------------------------------------------------------- #
# 2) 上位ラスパイレス集計
# --------------------------------------------------------------------------- #
def aggregate_laspeyres(elementary: dict[str, float], weights: dict[str, float]) -> float:
    """中分類別相対を CPI ウェイトでラスパイレス加重して上位集計する（§6-2）。

    weights は内部で（elementary に存在する category について）正規化する。
    """
    num = 0.0
    den = 0.0
    for category, relative in elementary.items():
        w = float(weights.get(category, 0.0))
        if w <= 0:
            continue
        num += w * relative
        den += w
    if den <= 0:
        return float("nan")
    return num / den


# --------------------------------------------------------------------------- #
# 3) 統括
# --------------------------------------------------------------------------- #
def _snapshot(df: pd.DataFrame, *, on: date, promo_mode: str) -> pd.DataFrame:
    """scrape_date == on のスナップショットを promo_mode で絞る。"""
    d = df.copy()
    d["scrape_date"] = pd.to_datetime(d["scrape_date"]).dt.date
    snap = d[d["scrape_date"] == on].copy()
    if promo_mode == "excl_promo" and "is_promo" in snap.columns:
        snap = snap[~snap["is_promo"].fillna(False).astype(bool)]
    return snap


def _base_prices(snap: pd.DataFrame) -> dict[str, float]:
    """基準期スナップショットから sku_key -> unit_price（同一 SKU は中央値）。"""
    d = snap.copy()
    d["unit_price"] = pd.to_numeric(d["unit_price"], errors="coerce")
    d = d[d["unit_price"] > 0]
    if len(d) == 0:
        return {}
    return {str(k): float(v) for k, v in d.groupby("sku_key")["unit_price"].median().items()}


def _base_categories(base_snap: pd.DataFrame, base_prices: dict[str, float]) -> set[str]:
    """基準期に有効な base price を持つ SKU が属する中分類（= バスケットの中分類）。"""
    if len(base_snap) == 0 or not base_prices:
        return set()
    d = base_snap[base_snap["sku_key"].astype(str).isin(base_prices)]
    return {str(c) for c in d["category"].dropna().unique()}


def _observation_dates(df: pd.DataFrame, *, after: date, before: date) -> list[date]:
    """after < d < before を満たす観測日を新しい順に返す（持ち越し元の探索用）。"""
    days = pd.to_datetime(df["scrape_date"]).dt.date.unique()
    return sorted({d for d in days if after < d < before}, reverse=True)


def _carry_forward(
    elementary: dict[str, float],
    *,
    df: pd.DataFrame,
    missing: set[str],
    base_prices: dict[str, float],
    base_date: date,
    as_of: date,
    promo_mode: str,
) -> dict[str, date]:
    """当日欠測の中分類を、直近で観測できた日の相対で埋める。

    elementary をその場で更新し、{category: 持ち越し元の観測日} を返す。基準日より後に
    一度も観測されていない中分類は埋めず、aggregate_laspeyres 側の平均代入に委ねる
    （「基準日から動いていない」という強い仮定を置かないため）。
    """
    carried: dict[str, date] = {}
    remaining = set(missing)
    for day in _observation_dates(df, after=base_date, before=as_of):
        if not remaining:
            break
        prior = jevons_elementary(
            _snapshot(df, on=day, promo_mode=promo_mode), base_prices=base_prices
        )
        for category in sorted(remaining & prior.keys()):
            elementary[category] = prior[category]
            carried[category] = day
            remaining.discard(category)
    return carried


def _compute_one(
    df: pd.DataFrame,
    *,
    as_of: date,
    base_date: date,
    base_value: float,
    promo_mode: str,
    weights: dict[str, float],
    methodology_version: str,
    imputation: str,
) -> dict[str, Any]:
    base_snap = _snapshot(df, on=base_date, promo_mode=promo_mode)
    asof_snap = _snapshot(df, on=as_of, promo_mode=promo_mode)
    base_prices = _base_prices(base_snap)

    elementary, counts = jevons_elementary(asof_snap, base_prices=base_prices, return_counts=True)
    observed = set(elementary)
    basket = _base_categories(base_snap, base_prices)
    missing = basket - observed

    carried: dict[str, date] = {}
    if imputation == "carry_forward" and missing:
        carried = _carry_forward(
            elementary,
            df=df,
            missing=missing,
            base_prices=base_prices,
            base_date=base_date,
            as_of=as_of,
            promo_mode=promo_mode,
        )

    relative = aggregate_laspeyres(elementary, weights)
    value = base_value * relative

    # 当日観測できていないウェイトの割合。指数がどれだけ代入に依存しているかの指標（§0）。
    basket_weight = sum(max(float(weights.get(c, 0.0)), 0.0) for c in basket)
    missing_weight = sum(max(float(weights.get(c, 0.0)), 0.0) for c in missing)
    imputed_weight_share = missing_weight / basket_weight if basket_weight > 0 else 0.0

    return {
        "index_code": "JP-INFL-FOOD",
        "date": as_of,
        "series_type": f"food_{promo_mode}",
        "value": value,
        "base_value": base_value,
        "base_date": base_date,
        "promo_mode": promo_mode,
        "n_items": int(sum(counts.values())),
        "imputation": imputation,
        "imputed_weight_share": imputed_weight_share,
        "imputed_categories": sorted(missing),
        "components": [
            {
                "category": c,
                "value": elementary[c],
                "n": counts.get(c),
                "weight": float(weights.get(c, 0.0)),
                "imputed": c not in observed,
                "imputed_from": carried[c].isoformat() if c in carried else None,
            }
            for c in sorted(elementary)
        ]
        + [
            # 平均代入に回った中分類（持ち越し元が無い）。値を持たないので別枠で明示する。
            {
                "category": c,
                "value": None,
                "n": 0,
                "weight": float(weights.get(c, 0.0)),
                "imputed": True,
                "imputed_from": None,
            }
            for c in sorted(missing - set(carried))
        ],
        "methodology_version": methodology_version,
    }


IMPUTATIONS = ("carry_forward", "mean")


def default_imputation() -> str:
    mode = str(_food_config().get("category_imputation", "carry_forward"))
    if mode not in IMPUTATIONS:
        raise ValueError(f"未知の category_imputation: {mode}")
    return mode


def compute(
    df: pd.DataFrame,
    *,
    as_of: date,
    base_date: date,
    base_value: float = 100.0,
    promo_mode: str | None = None,
    methodology_version: str = "",
    weights: dict[str, float] | None = None,
    imputation: str | None = None,
) -> dict[str, Any]:
    """食料指数値（IndexValue 相当 dict）を返す（§6-2）。

    - df から基準期/当期スナップショットを scrape_date で抽出。
    - promo_mode: 'excl_promo'（既定, is_promo 除外）/ 'incl_promo'（全件）/ 'both'。
      None のときは config の default_promo_mode を使う。
    - base_prices（sku_key -> 基準期 unit_price）を内部生成し
      jevons_elementary -> aggregate_laspeyres -> × base_value で指数化。
    - imputation: 'carry_forward'（既定, 当日欠測の中分類は直近観測日の相対を持ち越す）/
      'mean'（欠測分類を落としてウェイト再正規化 = 平均代入。旧挙動）。
      None のときは config の category_imputation を使う。
    - 'both' は {'excl_promo': dict, 'incl_promo': dict} を返す。
    """
    if promo_mode is None:
        promo_mode = default_promo_mode()
    if weights is None:
        weights = category_weights()
    if imputation is None:
        imputation = default_imputation()
    if imputation not in IMPUTATIONS:
        raise ValueError(f"未知の imputation: {imputation}")

    modes = ("excl_promo", "incl_promo") if promo_mode == "both" else (promo_mode,)
    results = {
        mode: _compute_one(
            df,
            as_of=as_of,
            base_date=base_date,
            base_value=base_value,
            promo_mode=mode,
            weights=weights,
            methodology_version=methodology_version,
            imputation=imputation,
        )
        for mode in modes
    }
    return results if promo_mode == "both" else results[promo_mode]
