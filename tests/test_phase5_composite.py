"""Phase 5 受け入れ条件のテスト（合成 + coverage, §0, §6-3）。

決定的・実通信なし。合成は「含まれるコンポーネント内で正規化加重」、
coverage_pct は CPI 総ウェイト 10000 に対する割合（正規化しない・必ず 100 未満）。
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
import yaml

from index_engine import composite

BASE_DATE = date(2025, 1, 1)
AS_OF = date(2025, 3, 1)

W_FOOD = 2626.0
W_HOUSING = 2087.0
WEIGHTS = {"JP-INFL-FOOD": W_FOOD, "JP-INFL-HOUSING": W_HOUSING}

FORBIDDEN = ["official", "公式 CPI", "公式CPI", "CPI そのもの", "CPIそのもの"]


def _components(food_value: float, housing_value: float) -> list[dict]:
    return [
        {"index_code": "JP-INFL-FOOD", "value": food_value, "yoy_pct": 3.0},
        {"index_code": "JP-INFL-HOUSING", "value": housing_value, "yoy_pct": 1.5},
    ]


# --------------------------------------------------------------------------- #
# 1) 再現性: 正規化加重平均に一致
# --------------------------------------------------------------------------- #
def test_compose_reproduces_normalized_weighted_mean() -> None:
    comps = _components(110.0, 104.0)
    result = composite.compose(
        comps, weights=WEIGHTS, base_date=BASE_DATE, as_of=AS_OF,
        base_value=100.0, methodology_version="v1",
    )
    expected = (110.0 * W_FOOD + 104.0 * W_HOUSING) / (W_FOOD + W_HOUSING)
    assert result["value"] == pytest.approx(expected, rel=1e-12)
    assert result["index_code"] == "JP-INFL-NOWCAST"
    assert result["promo_mode"] == "excl_promo"

    # components は正規化後ウェイト（合計 1）。
    norm = {c["code"]: c["weight"] for c in result["components"]}
    assert norm["JP-INFL-FOOD"] == pytest.approx(W_FOOD / (W_FOOD + W_HOUSING))
    assert sum(norm.values()) == pytest.approx(1.0)
    assert result["components"][0]["yoy_pct"] == 3.0


# --------------------------------------------------------------------------- #
# 2) coverage: (2626+2087)/10000×100 ≈ 47.13、必ず 100 未満
# --------------------------------------------------------------------------- #
def test_coverage_pct_matches_and_below_100() -> None:
    cov = composite.coverage_pct(WEIGHTS)
    assert cov == pytest.approx(47.13, abs=0.01)
    assert cov < 100.0


def test_coverage_uses_config_weights() -> None:
    """config/baskets.yaml の composite_weights と整合すること。"""
    data = yaml.safe_load(
        (Path(__file__).resolve().parent.parent / "config" / "baskets.yaml").read_text(
            encoding="utf-8"
        )
    )
    cw = {k: float(v) for k, v in data["composite_weights"].items()}
    cov = composite.coverage_pct(cw)
    assert cov < 100.0
    assert cov == pytest.approx(sum(cw.values()) / 10000.0 * 100.0)


# --------------------------------------------------------------------------- #
# 3) 表記: composite_partial / coverage < 100 / 公式CPI 誤認なし
# --------------------------------------------------------------------------- #
def test_notation_no_official_cpi_misrepresentation() -> None:
    result = composite.compose(
        _components(110.0, 104.0), weights=WEIGHTS, base_date=BASE_DATE,
        as_of=AS_OF, methodology_version="v1",
    )
    assert result["series_type"] == "composite_partial"
    assert result["coverage_pct"] is not None
    assert result["coverage_pct"] < 100.0

    # 文字列フィールドに禁止表記が無い。
    text_blob = " ".join(
        str(result[k]) for k in ("index_code", "series_type", "note")
    )
    for bad in FORBIDDEN:
        assert bad not in text_blob


# --------------------------------------------------------------------------- #
# 4) 加重変化: ウェイトを変えると合成 value が動く
# --------------------------------------------------------------------------- #
def test_weight_change_moves_value() -> None:
    comps = _components(110.0, 104.0)
    food_heavy = composite.compose(
        comps, weights={"JP-INFL-FOOD": 9.0, "JP-INFL-HOUSING": 1.0},
        base_date=BASE_DATE, as_of=AS_OF, methodology_version="v1",
    )
    housing_heavy = composite.compose(
        comps, weights={"JP-INFL-FOOD": 1.0, "JP-INFL-HOUSING": 9.0},
        base_date=BASE_DATE, as_of=AS_OF, methodology_version="v1",
    )
    assert food_heavy["value"] == pytest.approx((110.0 * 9 + 104.0) / 10.0)
    assert housing_heavy["value"] == pytest.approx((110.0 + 104.0 * 9) / 10.0)
    assert food_heavy["value"] > housing_heavy["value"]  # food のほうが高い


# --------------------------------------------------------------------------- #
# 5) 単一コンポーネント: 片方だけでも動き coverage がその分
# --------------------------------------------------------------------------- #
def test_single_component_coverage() -> None:
    comps = [{"index_code": "JP-INFL-FOOD", "value": 110.0}]
    result = composite.compose(
        comps, weights=WEIGHTS, base_date=BASE_DATE, as_of=AS_OF,
        methodology_version="v1",
    )
    assert result["value"] == pytest.approx(110.0)  # 単一なので value そのまま
    assert len(result["components"]) == 1
    assert result["components"][0]["weight"] == pytest.approx(1.0)
    # coverage は FOOD 分のみ。
    assert result["coverage_pct"] == pytest.approx(W_FOOD / 10000.0 * 100.0)
    assert result["coverage_pct"] < 100.0
