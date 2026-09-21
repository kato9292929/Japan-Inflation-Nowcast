"""Phase 4 受け入れ条件のテスト（食料指数, §6-2）。

実通信なし・決定的。合成データの category は baskets.yaml の food.categories と整合。
生平均は使わない（Jevons 幾何平均 + 上位ラスパイレス）。
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from index_engine import food

BASE_DATE = date(2025, 1, 1)
AS_OF = date(2025, 3, 1)


def _row(scrape_date, sku_key, unit_price, category, is_promo=False) -> dict:
    return {
        "scrape_date": scrape_date,
        "sku_key": sku_key,
        "unit_price": unit_price,
        "category": category,
        "is_promo": is_promo,
    }


# --------------------------------------------------------------------------- #
# 1) homogeneity: 全 SKU ×1.05 -> 指数 +5%
# --------------------------------------------------------------------------- #
def test_food_homogeneity_plus_5pct() -> None:
    base = [
        _row(BASE_DATE, "g1", 50.0, "穀類"),
        _row(BASE_DATE, "g2", 60.0, "穀類"),
        _row(BASE_DATE, "m1", 20.0, "乳卵類"),
        _row(BASE_DATE, "m2", 25.0, "乳卵類"),
    ]
    current = [
        _row(AS_OF, "g1", 52.5, "穀類"),
        _row(AS_OF, "g2", 63.0, "穀類"),
        _row(AS_OF, "m1", 21.0, "乳卵類"),
        _row(AS_OF, "m2", 26.25, "乳卵類"),
    ]
    df = pd.DataFrame(base + current)
    result = food.compute(df, as_of=AS_OF, base_date=BASE_DATE, base_value=100.0,
                          promo_mode="excl_promo", methodology_version="v1")
    assert result["index_code"] == "JP-INFL-FOOD"
    assert result["promo_mode"] == "excl_promo"
    assert result["value"] == pytest.approx(105.0, rel=1e-9)
    assert result["n_items"] == 4


# --------------------------------------------------------------------------- #
# 2) composition invariance: matched 価格不変・品揃え変化 -> 不変
# --------------------------------------------------------------------------- #
def test_food_composition_invariance() -> None:
    base = [
        _row(BASE_DATE, "g1", 50.0, "穀類"),
        _row(BASE_DATE, "g2", 60.0, "穀類"),
        _row(BASE_DATE, "m1", 20.0, "乳卵類"),
        _row(BASE_DATE, "m2", 25.0, "乳卵類"),
    ]
    # 当期: g2 が消失、新規 g3 が登場（base に無い）、m1 を重複。matched 価格は不変。
    current = [
        _row(AS_OF, "g1", 50.0, "穀類"),
        _row(AS_OF, "g3", 999.0, "穀類"),   # 新規（base に無い -> 除外）
        _row(AS_OF, "m1", 20.0, "乳卵類"),
        _row(AS_OF, "m1", 20.0, "乳卵類"),   # 重複（件数比だけ変化）
        _row(AS_OF, "m2", 25.0, "乳卵類"),
    ]
    df = pd.DataFrame(base + current)
    result = food.compute(df, as_of=AS_OF, base_date=BASE_DATE, base_value=100.0,
                          promo_mode="excl_promo", methodology_version="v1")
    assert result["value"] == pytest.approx(100.0, rel=1e-9)


# --------------------------------------------------------------------------- #
# 3) 特売: excl_promo と incl_promo が異なる
# --------------------------------------------------------------------------- #
def test_food_promo_excl_vs_incl_differ() -> None:
    base = [
        _row(BASE_DATE, "n1", 50.0, "穀類", is_promo=False),
        _row(BASE_DATE, "p1", 100.0, "菓子類", is_promo=False),
    ]
    current = [
        _row(AS_OF, "n1", 50.0, "穀類", is_promo=False),   # 不変
        _row(AS_OF, "p1", 80.0, "菓子類", is_promo=True),   # 特売 -20%
    ]
    df = pd.DataFrame(base + current)

    both = food.compute(df, as_of=AS_OF, base_date=BASE_DATE, base_value=100.0,
                        promo_mode="both", methodology_version="v1")
    excl = both["excl_promo"]
    incl = both["incl_promo"]

    # excl: 特売 p1 を除外 -> 穀類のみ matched -> 100。
    assert excl["value"] == pytest.approx(100.0, rel=1e-9)
    # incl: p1 を含む -> (穀類1.0 + 菓子類0.8)/2 = 0.9 -> 90。
    assert incl["value"] == pytest.approx(90.0, rel=1e-9)
    assert excl["value"] != pytest.approx(incl["value"])


# --------------------------------------------------------------------------- #
# 4) category 加重: ウェイトを変えると合成相対が変わる
# --------------------------------------------------------------------------- #
def test_food_category_weighting() -> None:
    base = [
        _row(BASE_DATE, "a", 100.0, "穀類"),
        _row(BASE_DATE, "b", 100.0, "乳卵類"),
    ]
    current = [
        _row(AS_OF, "a", 110.0, "穀類"),   # relative 1.1
        _row(AS_OF, "b", 100.0, "乳卵類"),  # relative 1.0
    ]
    df = pd.DataFrame(base + current)

    equal = food.compute(df, as_of=AS_OF, base_date=BASE_DATE, base_value=100.0,
                         promo_mode="excl_promo", methodology_version="v1",
                         weights={"穀類": 1.0, "乳卵類": 1.0})
    skewed = food.compute(df, as_of=AS_OF, base_date=BASE_DATE, base_value=100.0,
                          promo_mode="excl_promo", methodology_version="v1",
                          weights={"穀類": 3.0, "乳卵類": 1.0})

    assert equal["value"] == pytest.approx(105.0, rel=1e-9)   # (1.1+1.0)/2
    assert skewed["value"] == pytest.approx(107.5, rel=1e-9)  # (3*1.1+1.0)/4


# --------------------------------------------------------------------------- #
# 5) Jevons は幾何平均（生平均ではない）
# --------------------------------------------------------------------------- #
def test_jevons_is_geometric_mean() -> None:
    # relative 2.0 と 0.5 -> 幾何平均 1.0（算術平均 1.25 ではない）。
    base_prices = {"s1": 100.0, "s2": 100.0}
    df = pd.DataFrame(
        [
            _row(AS_OF, "s1", 200.0, "穀類"),
            _row(AS_OF, "s2", 50.0, "穀類"),
        ]
    )
    elementary = food.jevons_elementary(df, base_prices=base_prices)
    assert elementary["穀類"] == pytest.approx(1.0, rel=1e-12)


# --------------------------------------------------------------------------- #
# 6) カテゴリ脱落: 観測→欠測の並びで指数が跳ねないこと
# --------------------------------------------------------------------------- #
MID_DATE = date(2025, 2, 1)


def _two_category_panel(fish_on_as_of: bool) -> pd.DataFrame:
    """穀類は終始 1.00、魚介類は MID_DATE で 1.20。AS_OF に魚介類を出すか選べる。"""
    rows = [
        _row(BASE_DATE, "g1", 100.0, "穀類"),
        _row(BASE_DATE, "f1", 100.0, "魚介類"),
        _row(MID_DATE, "g1", 100.0, "穀類"),
        _row(MID_DATE, "f1", 120.0, "魚介類"),
        _row(AS_OF, "g1", 100.0, "穀類"),
    ]
    if fish_on_as_of:
        rows.append(_row(AS_OF, "f1", 120.0, "魚介類"))
    return pd.DataFrame(rows)


def _compute(df: pd.DataFrame, on: date, imputation: str) -> dict:
    return food.compute(
        df, as_of=on, base_date=BASE_DATE, base_value=100.0, promo_mode="excl_promo",
        methodology_version="v1", weights={"穀類": 1.0, "魚介類": 1.0}, imputation=imputation,
    )


def test_mean_imputation_jumps_when_category_drops_out() -> None:
    """旧挙動の記録。魚介類が落ちるだけで価格が動いていないのに指数が 110 -> 100 へ跳ぶ。"""
    observed = _compute(_two_category_panel(True), AS_OF, "mean")["value"]
    dropped = _compute(_two_category_panel(False), AS_OF, "mean")["value"]
    assert observed == pytest.approx(110.0)
    assert dropped == pytest.approx(100.0)
    assert observed - dropped == pytest.approx(10.0)


def test_carry_forward_keeps_index_continuous_on_dropout() -> None:
    """既定挙動。魚介類が当日欠測でも直近観測（MID_DATE の 1.20）を持ち越し、跳ねない。"""
    observed = _compute(_two_category_panel(True), AS_OF, "carry_forward")
    dropped = _compute(_two_category_panel(False), AS_OF, "carry_forward")
    assert observed["value"] == pytest.approx(110.0)
    assert dropped["value"] == pytest.approx(110.0)

    # 持ち越したことは必ず出力に出る（§0 透明性）。観測 SKU 数には数えない。
    assert dropped["imputed_categories"] == ["魚介類"]
    assert dropped["imputed_weight_share"] == pytest.approx(0.5)
    assert dropped["n_items"] == 1
    fish = next(c for c in dropped["components"] if c["category"] == "魚介類")
    assert fish["imputed"] is True
    assert fish["imputed_from"] == MID_DATE.isoformat()
    assert fish["value"] == pytest.approx(1.20)

    # 当日観測できた日は代入扱いにしない。
    assert observed["imputed_categories"] == []
    assert observed["imputed_weight_share"] == pytest.approx(0.0)
    assert all(c["imputed"] is False for c in observed["components"])


def test_carry_forward_falls_back_to_mean_when_never_observed() -> None:
    """基準日より後に一度も観測が無い中分類は持ち越さず、平均代入（=除外）に戻す。"""
    df = pd.DataFrame([
        _row(BASE_DATE, "g1", 100.0, "穀類"),
        _row(BASE_DATE, "f1", 100.0, "魚介類"),
        _row(AS_OF, "g1", 105.0, "穀類"),
    ])
    result = _compute(df, AS_OF, "carry_forward")
    assert result["value"] == pytest.approx(105.0)
    assert result["imputed_categories"] == ["魚介類"]
    assert result["imputed_weight_share"] == pytest.approx(0.5)
    fish = next(c for c in result["components"] if c["category"] == "魚介類")
    assert fish["value"] is None
    assert fish["imputed"] is True
    assert fish["imputed_from"] is None
