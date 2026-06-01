"""対外検証バックテスト（§9 Phase 7）。

算出系列の YoY を、手動投入の総務省公式系列（CSV）と比較する。実通信しない。
対応（運用者が CSV の code を合わせる）:
- JP-INFL-FOOD     ↔ 総務省「食料」
- JP-INFL-HOUSING  ↔ 総務省「民営家賃」
- JP-INFL-NOWCAST  ↔ 「食料 + 住居」加重

出力: 系列ごとの乖離（平均/最大）と方向一致率を含む検証レポート（構造化 + テキスト）。
外部公式データは CSV パス（引数）で受ける。CSV カラム: date, code, value（指数水準）。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

# 算出系列 -> 公式系列の対応（ドキュメント用。CSV の code はこの左辺に合わせる）。
SERIES_MAP = {
    "JP-INFL-FOOD": "総務省 CPI 食料",
    "JP-INFL-HOUSING": "総務省 CPI 民営家賃",
    "JP-INFL-NOWCAST": "総務省 CPI 食料+住居 加重",
}


@dataclass
class SeriesReport:
    """1 系列の検証結果。"""

    code: str
    official_label: str
    n: int
    mean_abs_dev_pp: float | None  # YoY 乖離の平均（百分点）
    max_abs_dev_pp: float | None
    direction_match_rate: float | None  # 方向一致率（0..1）


def yoy(df: pd.DataFrame) -> pd.DataFrame:
    """指数水準 df(date,value) から前年比 YoY(%) を計算する（365 日前を asof 参照）。"""
    d = df.copy()
    d["date"] = pd.to_datetime(d["date"])
    d = d.sort_values("date").set_index("date")
    s = pd.to_numeric(d["value"], errors="coerce").dropna()

    out_dates: list[Any] = []
    out_yoy: list[float] = []
    first = s.index.min()
    for ts, val in s.items():
        target = ts - pd.Timedelta(days=365)
        if target < first:
            continue
        prior = s.asof(target)
        if prior is None or pd.isna(prior) or prior == 0:
            continue
        out_dates.append(ts)
        out_yoy.append((float(val) / float(prior) - 1.0) * 100.0)
    return pd.DataFrame({"date": out_dates, "yoy_pct": out_yoy})


def load_official_csv(path: str | Path) -> dict[str, pd.DataFrame]:
    """公式系列 CSV（date, code, value）を code -> df(date,value) に読み込む。"""
    raw = pd.read_csv(path)
    result: dict[str, pd.DataFrame] = {}
    for code, grp in raw.groupby("code"):
        result[str(code)] = grp[["date", "value"]].reset_index(drop=True)
    return result


def _compare_one(code: str, computed: pd.DataFrame, official: pd.DataFrame) -> SeriesReport:
    c = yoy(computed).rename(columns={"yoy_pct": "computed"})
    o = yoy(official).rename(columns={"yoy_pct": "official"})
    label = SERIES_MAP.get(code, code)
    if c.empty or o.empty:
        return SeriesReport(code, label, 0, None, None, None)

    c = c.sort_values("date")
    o = o.sort_values("date")
    merged = pd.merge_asof(o, c, on="date", direction="nearest").dropna()
    if merged.empty:
        return SeriesReport(code, label, 0, None, None, None)

    dev = (merged["computed"] - merged["official"]).abs()
    direction = np.sign(merged["computed"]) == np.sign(merged["official"])
    return SeriesReport(
        code=code,
        official_label=label,
        n=int(len(merged)),
        mean_abs_dev_pp=float(dev.mean()),
        max_abs_dev_pp=float(dev.max()),
        direction_match_rate=float(direction.mean()),
    )


def backtest(
    computed: dict[str, pd.DataFrame], official: dict[str, pd.DataFrame]
) -> dict[str, Any]:
    """算出系列と公式系列を突き合わせ、検証レポート（構造化 + テキスト）を返す。"""
    reports: list[SeriesReport] = []
    for code in sorted(set(computed) & set(official)):
        reports.append(_compare_one(code, computed[code], official[code]))

    lines = ["# Validation report (YoY vs 総務省 公式系列)", ""]
    for r in reports:
        if r.n == 0:
            lines.append(f"- {r.code} ({r.official_label}): 比較可能な重複なし")
            continue
        lines.append(
            f"- {r.code} ({r.official_label}): n={r.n}, "
            f"mean|Δ|={r.mean_abs_dev_pp:.2f}pp, max|Δ|={r.max_abs_dev_pp:.2f}pp, "
            f"direction_match={r.direction_match_rate:.0%}"
        )

    return {
        "series": [asdict(r) for r in reports],
        "text": "\n".join(lines),
    }


def run_from_csv(
    computed: dict[str, pd.DataFrame], official_csv: str | Path
) -> dict[str, Any]:
    """公式 CSV パスから検証を実行するヘルパ。"""
    return backtest(computed, load_official_csv(official_csv))
