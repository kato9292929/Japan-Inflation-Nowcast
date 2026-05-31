"""Phase 2 受け入れ条件のテスト（住居指数, §6-1, §6-4）。

実通信なし・決定的。合成データは「真のヘドニック面」から無ノイズ生成するため、
OLS は係数を厳密復元でき、構成バイアス耐性を厳密に検証できる。
カテゴリ（ward/madori/structure/age_band/walk_band）は config の representative_units と
整合させ、予測が安定するようにする。
"""

from __future__ import annotations

import math
from datetime import date

import pandas as pd
import pytest

from index_engine import aggregate, flow, hedonic, laspeyres

# --- 真のヘドニック面（無ノイズ）------------------------------------------- #
WARDS = ["placeholder", "B"]
MADORI = {"1K": 25.0, "1LDK": 40.0, "2LDK": 55.0}
AGES = [1, 2]
WALKS = [0, 1]
FLOORS = [2, 3, 4, 5]
STRUCT = "RC"

B0, B_LA, B_FLOOR = 10.0, 0.7, 0.01
WARD_EFF = {"placeholder": 0.0, "B": 0.10}
MAD_EFF = {"1K": 0.0, "1LDK": 0.15, "2LDK": 0.25}
AGE_EFF = {1: 0.0, 2: -0.05}
WALK_EFF = {0: 0.0, 1: -0.03}

BASE_DATE = date(2025, 1, 1)
AS_OF = date(2025, 3, 1)  # 28 日窓が基準窓と重ならないよう離す


def _true_ln_rent(area, floor, ward, madori, age, walk) -> float:
    return (
        B0
        + B_LA * math.log(area)
        + B_FLOOR * floor
        + WARD_EFF[ward]
        + MAD_EFF[madori]
        + AGE_EFF[age]
        + WALK_EFF[walk]
    )


def _make_rows(
    date_val: date,
    *,
    price_mult: float = 1.0,
    first_seen: date | None = None,
    dup_2ldk: int = 1,
) -> list[dict]:
    """真の面から行を生成。price_mult で一律倍率、dup_2ldk で 2LDK の構成比だけ変える。"""
    rows: list[dict] = []
    fs = first_seen or date_val
    for ward in WARDS:
        for madori, base_area in MADORI.items():
            for age in AGES:
                for walk in WALKS:
                    for floor in FLOORS:
                        area = base_area + floor * 0.5
                        rent = math.exp(_true_ln_rent(area, floor, ward, madori, age, walk))
                        rent *= price_mult
                        row = {
                            "date": date_val,
                            "first_seen": fs,
                            "is_active": True,
                            "ward": ward,
                            "madori": madori,
                            "structure": STRUCT,
                            "age_band": age,
                            "walk_band": walk,
                            "floor": floor,
                            "area_m2": area,
                            "rent_total": rent,
                            "log_area": math.log(area),
                            "rent_per_m2": rent / area,
                        }
                        reps = dup_2ldk if madori == "2LDK" else 1
                        rows.extend(dict(row) for _ in range(reps))
    return rows


# --------------------------------------------------------------------------- #
# 1) ヘドニック: homogeneity（一律 +5% -> 指数 +5%）
# --------------------------------------------------------------------------- #
def test_hedonic_homogeneity_plus_5pct() -> None:
    df = pd.DataFrame(
        _make_rows(BASE_DATE, price_mult=1.0) + _make_rows(AS_OF, price_mult=1.05)
    )
    result = hedonic.compute(df, as_of=AS_OF, base_value=100.0, base_date=BASE_DATE)
    assert result["series_type"] == "stock_hedonic"
    assert result["value"] == pytest.approx(105.0, rel=1e-6)


# --------------------------------------------------------------------------- #
# 2) ヘドニック: composition invariance（価格不変・構成のみ変化 -> 不変）
# --------------------------------------------------------------------------- #
def test_hedonic_composition_invariance() -> None:
    df = pd.DataFrame(
        _make_rows(BASE_DATE, price_mult=1.0)
        + _make_rows(AS_OF, price_mult=1.0, dup_2ldk=3)  # 広い物件の比率だけ増やす
    )
    result = hedonic.compute(df, as_of=AS_OF, base_value=100.0, base_date=BASE_DATE)
    assert result["value"] == pytest.approx(100.0, rel=1e-6)


# --------------------------------------------------------------------------- #
# 2b) ラスパイレス: composition invariance + homogeneity
# --------------------------------------------------------------------------- #
def test_laspeyres_composition_invariance() -> None:
    base_df = pd.DataFrame(_make_rows(BASE_DATE, price_mult=1.0))
    base_cells, weights = laspeyres.stratify(base_df)

    df = pd.DataFrame(
        _make_rows(BASE_DATE, price_mult=1.0)
        + _make_rows(AS_OF, price_mult=1.0, dup_2ldk=4)  # 構成だけ変える
    )
    result = laspeyres.compute(
        df, as_of=AS_OF, base_cells=base_cells, weights=weights, base_date=BASE_DATE
    )
    assert result["series_type"] == "stock_laspeyres"
    assert result["value"] == pytest.approx(100.0, rel=1e-9)


def test_laspeyres_homogeneity_plus_5pct() -> None:
    base_df = pd.DataFrame(_make_rows(BASE_DATE, price_mult=1.0))
    base_cells, weights = laspeyres.stratify(base_df)

    df = pd.DataFrame(
        _make_rows(BASE_DATE, price_mult=1.0) + _make_rows(AS_OF, price_mult=1.05)
    )
    result = laspeyres.compute(
        df, as_of=AS_OF, base_cells=base_cells, weights=weights, base_date=BASE_DATE
    )
    assert result["value"] == pytest.approx(105.0, rel=1e-9)


# --------------------------------------------------------------------------- #
# 3) フロー: 新規掲載のみを拾い、既存掲載に影響されない
# --------------------------------------------------------------------------- #
def test_flow_uses_only_new_listings() -> None:
    # 基準期の新規掲載（rpm=5000）
    base_new = [
        {"first_seen": BASE_DATE, "date": BASE_DATE, "area_m2": 25.0,
         "rent_total": 5000.0 * 25.0, "rent_per_m2": 5000.0},
        {"first_seen": BASE_DATE, "date": BASE_DATE, "area_m2": 40.0,
         "rent_total": 5000.0 * 40.0, "rent_per_m2": 5000.0},
    ]
    # as_of の新規掲載（rpm=5250 = +5%）
    asof_new = [
        {"first_seen": AS_OF, "date": AS_OF, "area_m2": 25.0,
         "rent_total": 5250.0 * 25.0, "rent_per_m2": 5250.0},
        {"first_seen": AS_OF, "date": AS_OF, "area_m2": 50.0,
         "rent_total": 5250.0 * 50.0, "rent_per_m2": 5250.0},
    ]
    # 既存掲載（first_seen が両日と異なる。全く別の rpm）
    existing = [
        {"first_seen": date(2024, 6, 1), "date": AS_OF, "area_m2": 30.0,
         "rent_total": 9999.0 * 30.0, "rent_per_m2": 9999.0},
    ]

    df_only_new = pd.DataFrame(base_new + asof_new)
    df_with_existing = pd.DataFrame(base_new + asof_new + existing)

    r1 = flow.compute(df_only_new, as_of=AS_OF, base_value=100.0, base_date=BASE_DATE)
    r2 = flow.compute(df_with_existing, as_of=AS_OF, base_value=100.0, base_date=BASE_DATE)

    assert r1["series_type"] == "flow"
    assert r1["value"] == pytest.approx(105.0, rel=1e-9)
    assert r1["n_new"] == 2
    # 既存掲載があっても結果は変わらない。
    assert r2["value"] == pytest.approx(r1["value"], rel=1e-12)
    assert r2["n_new"] == 2


# --------------------------------------------------------------------------- #
# 4) aggregate: smooth / change_rates / finalize
# --------------------------------------------------------------------------- #
def test_smooth_trailing_mean() -> None:
    idx = pd.to_datetime(["2025-01-01", "2025-01-02", "2025-01-03"])
    s = pd.Series([100.0, 110.0, 120.0], index=idx)
    out = aggregate.smooth(s, window_days=7)
    assert out.iloc[0] == pytest.approx(100.0)
    assert out.iloc[-1] == pytest.approx(110.0)  # (100+110+120)/3


def test_change_rates_insufficient_history_is_none() -> None:
    idx = pd.date_range("2025-05-01", periods=10, freq="D")
    s = pd.Series([100.0 + i for i in range(10)], index=idx)
    rates = aggregate.change_rates(s)
    assert rates["yoy_pct"] is None
    assert rates["mom_pct"] is None
    assert rates["wow_pct"] is not None  # 7 日前は履歴内


def test_change_rates_yoy_computed() -> None:
    idx = pd.to_datetime(["2024-05-31", "2025-05-31"])
    s = pd.Series([100.0, 110.0], index=idx)
    rates = aggregate.change_rates(s)
    assert rates["yoy_pct"] == pytest.approx(10.0)


def test_finalize_attaches_version_and_divergence() -> None:
    value = {"value": 105.0, "series_type": "stock_hedonic", "date": AS_OF}
    out = aggregate.finalize(value, methodology_version="v1", crosscheck_value=100.0)
    assert out["methodology_version"] == "v1"
    assert out["series_type"] == "stock_hedonic"
    assert out["divergence_pct"] == pytest.approx(5.0)

    out2 = aggregate.finalize(value, methodology_version="v1")
    assert out2["divergence_pct"] is None
