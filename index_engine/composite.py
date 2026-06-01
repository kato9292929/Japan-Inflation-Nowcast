"""合成ナウキャスト JP-INFL-NOWCAST（§6-3）。

- FOOD と HOUSING を CPI 費目ウェイト（config/baskets.yaml の composite_weights）で
  「含まれるコンポーネント内で正規化」して加重平均する。
- series_type='composite_partial'、coverage_pct、components（code, 正規化後 weight,
  value, あれば yoy）を付与。
- 合成に使う食料系列は promo_mode で切替（既定 excl_promo）。

非交渉制約（§0）: これは部分カバーの「ナウキャスト/速報」であり「公式 CPI」ではない。
coverage_pct を必ず付け（常に 100 未満）、誤認させる表記をしない。

重要な区別:
- value は構成ウェイトを「含まれるコンポーネント内で正規化」して加重平均する。
- coverage_pct は正規化しない。CPI 総ウェイト 10000 に対する構成ウェイト合計の割合
  （= Σweights / 10000 × 100、約 47.13）。これは「CPI バスケットのどれだけをカバー
  しているか」を示す正直な値で、必ず 100 未満。
"""

from __future__ import annotations

from datetime import date
from typing import Any

# CPI 総ウェイト（10000 分比）。coverage_pct の分母（§6-3）。
CPI_TOTAL_WEIGHT = 10000.0


def coverage_pct(weights: dict[str, float]) -> float:
    """合成のカバー率（= 構成ウェイト合計 / CPI 総ウェイト × 100）を返す（§6-3）。

    正規化しない。常に 100 未満（部分カバー, §0）。
    """
    return sum(float(w) for w in weights.values()) / CPI_TOTAL_WEIGHT * 100.0


def _component_code(comp: dict[str, Any]) -> str | None:
    return comp.get("index_code") or comp.get("code")


def compose(
    components: list[dict[str, Any]],
    *,
    weights: dict[str, float],
    base_date: date,
    base_value: float = 100.0,
    methodology_version: str = "",
    promo_mode: str = "excl_promo",
    as_of: date | None = None,
) -> dict[str, Any]:
    """コンポーネント指数値から合成（IndexValue 相当 dict）を返す（§0, §6-3）。

    - 含まれるコンポーネントのウェイトで正規化加重して合成 value を算出。
    - coverage_pct(weights) は当該コンポーネントの CPI ウェイト合計分のみで付与
      （単一コンポーネントならその分だけ）。
    """
    # 値があり、かつウェイトが定義されているコンポーネントだけを採用。
    included: list[tuple[str, dict[str, Any], float]] = []
    for comp in components:
        code = _component_code(comp)
        value = comp.get("value")
        if code is None or value is None or code not in weights:
            continue
        w = float(weights[code])
        if w <= 0:
            continue
        included.append((code, comp, w))

    if not included:
        raise ValueError("compose: 採用可能なコンポーネントがありません")

    total_w = sum(w for _, _, w in included)
    value = sum(float(comp["value"]) * w for _, comp, w in included) / total_w

    # 採用コンポーネントのウェイトだけで coverage を出す（部分カバー, §0）。
    included_weights = {code: w for code, _, w in included}
    cov = coverage_pct(included_weights)

    out_components = []
    for code, comp, w in included:
        entry: dict[str, Any] = {
            "code": code,
            "weight": w / total_w,  # 含まれるコンポーネント内で正規化
            "value": float(comp["value"]),
        }
        if comp.get("yoy_pct") is not None:
            entry["yoy_pct"] = comp["yoy_pct"]
        elif comp.get("yoy") is not None:
            entry["yoy_pct"] = comp["yoy"]
        out_components.append(entry)

    # §0 遵守: 「公式 CPI」と誤認させない、部分カバーの速報であることを明示する説明文。
    note = (
        f"独立系インフレ・ナウキャスト（速報）。CPI バスケットの約 {cov:.1f}% を"
        "カバーする部分指数。"
    )

    return {
        "index_code": "JP-INFL-NOWCAST",
        "date": as_of,
        "freq": "D",
        "series_type": "composite_partial",
        "value": value,
        "base_value": base_value,
        "base_date": base_date,
        "coverage_pct": cov,
        "components": out_components,
        "promo_mode": promo_mode,
        "methodology_version": methodology_version,
        "note": note,
    }
