#!/usr/bin/env python3
"""
spread_monitor — JINのdaily出力に足す「上流CGPI vs 下流retail の乖離(gap)」ブロック生成。

思想:
  上流CGPI(企業物価)のYoYは既に高い。下流(店頭実勢=JIN index)がそこにどこまで
  追いついたか＝「転嫁の残り燃料」を毎日1ブロックで可視化する。
  lag/転嫁率の推定(cgpi_passthrough.py)はデータが約9ヶ月貯まるまで保留。こちらは初日から出せる。

誠実な設計上の注意:
  - CGPI YoY(12ヶ月変化) と JIN短期ドリフト(数日〜数週の年率換算)は本来 apples-to-oranges。
    なので gap は「精密な数値」ではなく方向性ウォッチ指標として maturity ラベル付きで出す。
  - JINが月次で貯まるほど downstream を MoM年率→YoY に格上げでき、gap が本物のYoY差に近づく。
  - short_window では数値gapを出さない(not_comparable)。上流YoYと base比実測の並置に留める。

入力(列名は引数で上書き可):
  CGPI: date + value(YoY%想定。levelなら --cgpi-mode level)
  JIN : date + value(Jevons index level, base日=100想定)

出力: passthrough_gap ブロック(dict/JSON)。jin-export-public が JINのpublic JSON に merge する。
"""
import argparse
import json
import sys
from datetime import datetime, timezone
import numpy as np
import pandas as pd


def load_series(path, date_col, value_col, name):
    df = pd.read_csv(path)
    if date_col not in df.columns or value_col not in df.columns:
        sys.exit(f"[{name}] 列なし date='{date_col}' value='{value_col}' / 実列={list(df.columns)}")
    df[date_col] = pd.to_datetime(df[date_col])
    s = df[[date_col, value_col]].dropna().set_index(date_col)[value_col].sort_index()
    return s


def to_yoy(level_monthly):
    return level_monthly.pct_change(12) * 100.0


def compute_spread(cgpi, jin, cgpi_mode="yoy", base_date=None, jin_monthly="mean"):
    # ---- upstream: CGPI 最新YoY ----
    cgpi_m = cgpi.resample("MS").last()
    cgpi_yoy = cgpi_m if cgpi_mode == "yoy" else to_yoy(cgpi_m)
    cgpi_yoy = cgpi_yoy.dropna()
    if cgpi_yoy.empty:
        up = None
    else:
        up = {"source": "CGPI", "as_of_month": str(cgpi_yoy.index[-1].date())[:7],
              "yoy_pct": round(float(cgpi_yoy.iloc[-1]), 2)}

    # ---- downstream: JIN retail ----
    jin = jin.dropna()
    if jin.empty:
        return {"passthrough_gap": {"error": "no_jin_data"}}
    latest_date, latest_idx = jin.index[-1], float(jin.iloc[-1])
    if base_date is not None:
        base_date = pd.to_datetime(base_date)
        prior = jin[jin.index <= base_date]
        base_idx = float(prior.iloc[-1]) if len(prior) else float(jin.iloc[0])
        base_used = base_date
    else:
        base_idx, base_used = float(jin.iloc[0]), jin.index[0]
    window_days = int((latest_date - base_used).days)

    cum_pct = (latest_idx / base_idx - 1) * 100.0 if base_idx else np.nan

    # JINが十分長ければ YoY / MoM年率。短窓では年率gapを出さない(ノイズで嘘になる)
    jin_m = jin.resample("MS").mean() if jin_monthly == "mean" else jin.resample("MS").last()
    n_months = jin_m.dropna().shape[0]
    if n_months >= 13:
        down_rate = round(float(to_yoy(jin_m).dropna().iloc[-1]), 2)
        basis, maturity = "yoy", "full_yoy"
    elif n_months >= 2:
        mom = jin_m.pct_change().dropna()
        down_rate = round(float(((1 + mom.iloc[-1]) ** 12 - 1) * 100.0), 2)
        basis, maturity = "mom_annualized", "maturing"
    else:
        # 短窓: 年率換算は嘘になるので rate は出さず、base比実測だけを主指標にする
        down_rate = None
        basis, maturity = "cum_since_base_only", "short_window"

    down = {"source": "JIN", "base_date": str(base_used.date()), "base_index": round(base_idx, 3),
            "latest_date": str(latest_date.date()), "latest_index": round(latest_idx, 3),
            "window_days": window_days,
            "cum_pct_since_base": round(cum_pct, 3) if not np.isnan(cum_pct) else None,
            "rate_pct": down_rate, "basis": basis}

    # ---- gap ----
    if not up:
        gap = None
    elif maturity == "short_window":
        # 数値gapは出さない。上流YoYと「base比実測」を並置するに留める。
        gap = {
            "status": "not_comparable",
            "upstream_minus_downstream_pt": None,
            "maturity": "short_window",
            "reading": (f"上流CGPI YoY {up['yoy_pct']:+.1f}% に対し、店頭は base比 "
                        f"{down['cum_pct_since_base']:+.2f}%({window_days}日)。"
                        "窓が短く年率比較は不能。転嫁の到達度はcum_pct_since_baseで追う。"),
            "caveat": "月次が2点貯まった時点でMoM年率のgap(maturing)に自動昇格する。",
        }
    elif down_rate is not None:
        gap_pt = round(up["yoy_pct"] - down_rate, 2)
        gap = {
            "status": "ok",
            "upstream_minus_downstream_pt": gap_pt,
            "maturity": maturity,
            "reading": ("上流CGPI YoY と下流インフレ率の差。プラスが大きいほど"
                        "『転嫁の残り燃料』が大きい＝店頭がまだ追いついていない"),
            "caveat": ("maturing: 下流はMoM年率。単月ぶれに注意。" if maturity == "maturing"
                       else "full_yoy: 上流・下流ともYoY。比較可能。"),
        }
    else:
        gap = None

    return {"passthrough_gap": {
        "as_of": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "upstream": up, "downstream": down, "gap": gap,
    }}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cgpi", required=True)
    ap.add_argument("--jin", required=True)
    ap.add_argument("--cgpi-date-col", default="date")
    ap.add_argument("--cgpi-col", default="value")
    ap.add_argument("--jin-date-col", default="date")
    ap.add_argument("--jin-col", default="value")
    ap.add_argument("--cgpi-mode", choices=["yoy", "level"], default="yoy")
    ap.add_argument("--base-date", default=None, help="JINのbase日(例 2026-06-04)。未指定なら最初の観測")
    ap.add_argument("--jin-monthly", choices=["last", "mean"], default="mean")
    ap.add_argument("--pretty", action="store_true")
    a = ap.parse_args()

    cgpi = load_series(a.cgpi, a.cgpi_date_col, a.cgpi_col, "cgpi")
    jin = load_series(a.jin, a.jin_date_col, a.jin_col, "jin")
    block = compute_spread(cgpi, jin, cgpi_mode=a.cgpi_mode,
                           base_date=a.base_date, jin_monthly=a.jin_monthly)
    print(json.dumps(block, ensure_ascii=False, indent=2 if a.pretty else None))


if __name__ == "__main__":
    main()
