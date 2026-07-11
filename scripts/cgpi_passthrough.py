#!/usr/bin/env python3
"""
CGPI -> Japan Inflation Nowcast (retail) passthrough / lead-lag analysis.

目的:
  上流 CGPI(企業物価) のインフレ率が、下流の店頭実勢(JINのretail index)に
  「何ヶ月遅れで」「どれだけの率で」転嫁されるかを推定する最小ツール。

  step 1 = このスクリプト:
    - 両系列を月次に揃える
    - lag k を振って corr(CGPI_infl(t-k), JIN_infl(t)) を出す
    - 最良lag で passthrough β を OLS 推定
    - データ長が足りなければ「係数を出さず」に不足を明示する（重要）

想定入力（列名は --*-col で上書き可）:
  CGPI CSV : date列 + value列（YoY% でも level でもよい。level なら --cgpi-mode level）
  JIN  CSV : date列 + value列（Jevons index level を想定。--jin-mode level）

実データ配線（このリポジトリ）:
  scripts/passthrough_prep.py が src/data/jin_public.json（series[].date/excl/incl, level）と
  data/macro_reference.parquet（series_id=cgpi_total, metric=yoy_pct, period/value）を
  date,value CSV に変換する。JIN は excl(基調)を既定。CGPI は yoy_pct。
"""
import argparse
import sys
import numpy as np
import pandas as pd


def load_series(path, date_col, value_col, name):
    df = pd.read_csv(path)
    if date_col not in df.columns or value_col not in df.columns:
        sys.exit(f"[{name}] 列が見つからない: date='{date_col}', value='{value_col}' / 実列={list(df.columns)}")
    df[date_col] = pd.to_datetime(df[date_col])
    s = df[[date_col, value_col]].dropna().set_index(date_col)[value_col].sort_index()
    s.name = name
    return s


def to_monthly(s, how="last"):
    # 日次/不規則を月次に。JINは月内複数点あるので月末値 or 月平均。
    return s.resample("MS").mean() if how == "mean" else s.resample("MS").last()


def to_yoy(level):
    return level.pct_change(12) * 100.0


def to_mom_annualized(level):
    return ((1 + level.pct_change()) ** 12 - 1) * 100.0


def ols(y, x):
    """単回帰 y = a + b x。numpyのみ。b, R2, t値, n を返す。"""
    m = (~np.isnan(x)) & (~np.isnan(y))
    x, y = x[m], y[m]
    n = len(x)
    if n < 3:
        return None
    X = np.column_stack([np.ones(n), x])
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    dof = n - 2
    if dof <= 0:
        return {"b": beta[1], "a": beta[0], "r2": np.nan, "t": np.nan, "n": n}
    sigma2 = (resid @ resid) / dof
    cov = sigma2 * np.linalg.inv(X.T @ X)
    se_b = np.sqrt(cov[1, 1])
    t = beta[1] / se_b if se_b > 0 else np.nan
    ss_tot = ((y - y.mean()) ** 2).sum()
    r2 = 1 - (resid @ resid) / ss_tot if ss_tot > 0 else np.nan
    return {"b": beta[1], "a": beta[0], "r2": r2, "t": t, "n": n, "se_b": se_b}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cgpi", required=True)
    ap.add_argument("--jin", required=True)
    ap.add_argument("--cgpi-date-col", default="date")
    ap.add_argument("--cgpi-col", default="value")
    ap.add_argument("--jin-date-col", default="date")
    ap.add_argument("--jin-col", default="value")
    ap.add_argument("--cgpi-mode", choices=["yoy", "level"], default="yoy",
                    help="CGPI列がYoY%ならyoy、指数levelならlevel（内部でYoY化）")
    ap.add_argument("--jin-mode", choices=["level", "yoy"], default="level")
    ap.add_argument("--jin-monthly", choices=["last", "mean"], default="mean")
    ap.add_argument("--infl", choices=["yoy", "mom_ann"], default="yoy",
                    help="転嫁を測る単位。データが1年未満ならyoyは作れないのでmom_ann推奨")
    ap.add_argument("--max-lag", type=int, default=6)
    ap.add_argument("--min-overlap", type=int, default=9,
                    help="lag推定に必要な最低重複月数。これ未満なら係数を出さない")
    ap.add_argument("--out", default=None, help="lag表のCSV出力先")
    a = ap.parse_args()

    cgpi_raw = load_series(a.cgpi, a.cgpi_date_col, a.cgpi_col, "cgpi")
    jin_raw = load_series(a.jin, a.jin_date_col, a.jin_col, "jin")

    # 月次化
    cgpi_m = to_monthly(cgpi_raw, "last")
    jin_m = to_monthly(jin_raw, a.jin_monthly)

    # CGPIをYoY%に統一
    cgpi_yoy = cgpi_m if a.cgpi_mode == "yoy" else to_yoy(cgpi_m)

    # JINをインフレ率に
    if a.jin_mode == "yoy":
        jin_infl = jin_m
    else:
        jin_infl = to_yoy(jin_m) if a.infl == "yoy" else to_mom_annualized(jin_m)

    # CGPI側もJINと同じ単位に寄せる（infl=mom_annのときはCGPIも月次変化ベースが理想だが、
    # 公式CGPIはYoYで来ることが多いので、ここではCGPI=YoY / JIN=選択単位 の非対称を許容し、
    # あくまで「上流の勢い」と「下流の勢い」の連動を見る設計）
    df = pd.concat([cgpi_yoy.rename("cgpi_infl"), jin_infl.rename("jin_infl")], axis=1)

    print("=" * 64)
    print("CGPI -> JIN passthrough / lead-lag  (step 1)")
    print("=" * 64)
    print(f"CGPI月次点: {cgpi_m.dropna().shape[0]}  期間 {cgpi_m.dropna().index.min().date()}..{cgpi_m.dropna().index.max().date()}")
    print(f"JIN 月次点: {jin_m.dropna().shape[0]}  期間 {jin_m.dropna().index.min().date()}..{jin_m.dropna().index.max().date()}")

    # spread monitor（今すぐ意味がある部分）
    print("\n-- spread monitor（上流YoY vs 下流インフレ率） --")
    spread = df.dropna()
    if spread.empty:
        print("  重複期間なし。JINが十分に伸びるまでlevelの並置のみ可能。")
    else:
        for dt, row in spread.tail(6).iterrows():
            print(f"  {dt.date()}  CGPI {row.cgpi_infl:+6.2f}%   JIN {row.jin_infl:+6.2f}%   gap {row.cgpi_infl-row.jin_infl:+6.2f}pt")

    # lag スキャン
    print("\n-- lag scan: corr(CGPI(t-k), JIN(t)) --")
    rows = []
    for k in range(0, a.max_lag + 1):
        joined = pd.concat([df["cgpi_infl"].shift(k).rename("x"), df["jin_infl"].rename("y")], axis=1).dropna()
        n = len(joined)
        if n >= 3:
            corr = joined["x"].corr(joined["y"])
            fit = ols(joined["y"].to_numpy(), joined["x"].to_numpy())
        else:
            corr, fit = np.nan, None
        rows.append({"lag_months": k, "n_overlap": n, "corr": corr,
                     "beta": fit["b"] if fit else np.nan,
                     "r2": fit["r2"] if fit else np.nan,
                     "t": fit["t"] if fit else np.nan})
        print(f"  k={k}m  n={n:2d}  corr={corr:+.3f}" if not np.isnan(corr) else f"  k={k}m  n={n:2d}  corr=NA")
    tab = pd.DataFrame(rows)

    # 十分性ゲート
    max_overlap = int(tab["n_overlap"].max())
    print("\n-- verdict --")
    if max_overlap < a.min_overlap:
        print(f"  X データ不足: 最大重複 {max_overlap}ヶ月 < 必要 {a.min_overlap}ヶ月。")
        print(f"     -> lag/転嫁率は推定しない（この長さで出る数字はノイズ）。")
        print(f"     -> 今できるのは上の spread monitor（勢いの乖離）まで。")
        print(f"     -> 月次点が {a.min_overlap}+ 貯まったら同じコマンドで係数が出る。")
    else:
        valid = tab[tab["n_overlap"] >= max(3, a.min_overlap // 2)].copy()
        best = valid.loc[valid["corr"].abs().idxmax()]
        lag_m, corr_v = int(best["lag_months"]), float(best["corr"])
        beta_v, r2_v, n_v = float(best["beta"]), float(best["r2"]), int(best["n_overlap"])
        print(f"  OK best lag = {lag_m}ヶ月  corr={corr_v:+.3f}  "
              f"passthrough beta={beta_v:+.3f}  R2={r2_v:.3f}  (n={n_v})")
        print(f"     解釈: 上流CGPIが1pt動くと、約{lag_m}ヶ月遅れで")
        print(f"           下流の食品インフレが約{beta_v:+.2f}pt動く（転嫁率{beta_v:.0%}相当）")

    if a.out:
        tab.to_csv(a.out, index=False)
        print(f"\n  lag表を書き出し: {a.out}")


if __name__ == "__main__":
    main()
