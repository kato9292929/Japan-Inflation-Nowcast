#!/usr/bin/env python3
"""passthrough 用データアダプタ（実データのみ・値は作らない）。

cgpi_passthrough.py が食う date,value CSV を、このリポジトリの実データ源から生成する:
  - JIN : src/data/jin_public.json の series[].date / (excl|incl)  … Jevons index level, base 100
  - CGPI: data/macro_reference.parquet の series_id=cgpi_total, metric=yoy_pct の period/value

JIN は既定で excl(基調・特売除外)。--jin-col incl で特売込。CGPI は既定 yoy_pct。
出力先の CSV は分析用の派生集計であり、生データの再配布ではない（§8）。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent


def jin_csv(out: Path, col: str) -> int:
    series = json.loads((ROOT / "src" / "data" / "jin_public.json").read_text())["series"]
    df = pd.DataFrame(series)[["date", col]].rename(columns={col: "value"})
    df = df.dropna()
    df.to_csv(out, index=False)
    return len(df)


def cgpi_csv(out: Path, series_id: str, metric: str) -> int:
    df = pd.read_parquet(ROOT / "data" / "macro_reference.parquet")
    sub = df[(df["series_id"] == series_id) & (df["metric"] == metric)].copy()
    sub["period"] = pd.to_datetime(sub["period"])
    # 遡及改訂(r)で同一 period に複数版がある場合は fetched_at が新しい方を採用。
    if "fetched_at" in sub.columns:
        sub = sub.sort_values(["period", "fetched_at"]).drop_duplicates("period", keep="last")
    o = sub.sort_values("period")[["period", "value"]].rename(columns={"period": "date"})
    o.to_csv(out, index=False)
    return len(o)


def main() -> None:
    ap = argparse.ArgumentParser(description="JIN/CGPI 実データ -> passthrough 用 date,value CSV")
    ap.add_argument("--outdir", default=".")
    ap.add_argument("--jin-col", choices=["excl", "incl"], default="excl",
                    help="基調=excl(既定) / 特売込=incl")
    ap.add_argument("--cgpi-series", default="cgpi_total")
    ap.add_argument("--cgpi-metric", default="yoy_pct")
    a = ap.parse_args()

    outdir = Path(a.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    nj = jin_csv(outdir / "jin.csv", a.jin_col)
    nc = cgpi_csv(outdir / "cgpi.csv", a.cgpi_series, a.cgpi_metric)
    print(f"jin.csv : {nj} rows (col={a.jin_col})            -> {outdir / 'jin.csv'}")
    print(f"cgpi.csv: {nc} rows ({a.cgpi_series}/{a.cgpi_metric}) -> {outdir / 'cgpi.csv'}")


if __name__ == "__main__":
    main()
