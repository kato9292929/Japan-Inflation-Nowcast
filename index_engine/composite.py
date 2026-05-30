"""合成ナウキャスト JP-INFL-NOWCAST（§6-3）。

- FOOD と HOUSING を CPI 費目ウェイト（config/baskets.yaml）で正規化加重。
- series_type='composite_partial'、coverage_pct（=食料+住居の CPI ウェイト合計）、
  components（code, weight, value, yoy）を付与。
- 合成に使う食料系列は promo_mode で切替（既定 excl_promo）。

非交渉制約（§0）: これは部分カバーの「ナウキャスト/速報」であり「公式 CPI」ではない。
coverage_pct を必ず付け、誤認させる表記をしない。
"""

from __future__ import annotations

from datetime import date
from typing import Any


def coverage_pct(weights: dict[str, float]) -> float:
    """合成のカバー率（= 構成ウェイト合計 / CPI 総ウェイト × 100）を返す。"""
    raise NotImplementedError("Phase 5: coverage_pct を実装する")


def compose(
    components: list[dict[str, Any]],
    *,
    weights: dict[str, float],
    as_of: date,
    base_date: date,
    promo_mode: str = "excl_promo",
) -> dict[str, Any]:
    """コンポーネント指数値から合成（IndexValue 相当 dict）を返す。

    series_type='composite_partial'、coverage_pct、components を必ず含める（§0, §6-3）。
    """
    raise NotImplementedError("Phase 5: 合成と coverage 付与を実装する")
