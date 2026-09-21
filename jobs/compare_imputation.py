"""カテゴリ脱落の代入方法を切り替えて、既存 DB の食料系列を再計算し差分を出す。

配信ファイルには一切書かない。読むだけ・印字するだけ。carry_forward（既定）に切り替えると
公開済みの系列がどれだけ動くかを、再公開の前に運用者が確認するために使う。

    uv run python -m jobs.compare_imputation
    uv run python -m jobs.compare_imputation --promo-mode incl_promo
"""

from __future__ import annotations

import argparse
from datetime import date

from index_engine import food
from jobs.export_public import _food_panel
from storage.db import get_session, get_settings


def _observation_dates(panel) -> list[date]:
    import pandas as pd

    return sorted(pd.to_datetime(panel["scrape_date"]).dt.date.unique())


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--promo-mode", choices=["excl_promo", "incl_promo"], default="excl_promo")
    parser.add_argument("--base-date", type=date.fromisoformat, default=None)
    args = parser.parse_args(argv)

    base_date = args.base_date or get_settings().base_date
    with get_session() as session:
        panel = _food_panel(session)
    if panel.empty:
        print("FoodClean が空です。先に観測 CSV を取り込んでください。")
        return 1

    header = (
        f"{'date':<12}{'mean(旧)':>10}{'carry(新)':>11}"
        f"{'差':>8}{'代入ウェイト':>14}  {'欠測中分類'}"
    )
    print(f"base_date={base_date}  promo_mode={args.promo_mode}")
    print(header)
    print("-" * (len(header) + 8))
    for day in _observation_dates(panel):
        if day <= base_date:
            continue
        rows = {
            mode: food.compute(
                panel, as_of=day, base_date=base_date, base_value=100.0,
                promo_mode=args.promo_mode, imputation=mode,
            )
            for mode in ("mean", "carry_forward")
        }
        old, new = rows["mean"]["value"], rows["carry_forward"]["value"]
        missing = rows["carry_forward"]["imputed_categories"]
        share = rows["carry_forward"]["imputed_weight_share"]
        print(
            f"{day.isoformat():<12}{old:>10.2f}{new:>11.2f}{new - old:>+8.2f}"
            f"{share:>13.1%}  {'・'.join(missing) or '-'}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
