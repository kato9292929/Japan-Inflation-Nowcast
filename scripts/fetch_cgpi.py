"""日本銀行「企業物価指数（CGPI）」国内企業物価指数・総合の月次 fetcher。

データソース（日本銀行）:
    ランディングページ: https://www.boj.or.jp/statistics/pi/cgpi_release/index.htm/
    時系列データ（フラットファイル）: 上記ページからリンクされる CSV。

    canonical CSV URL（既定値）:
        https://www.boj.or.jp/statistics/pi/cgpi_release/cgpi2020.csv
    ※ このサンドボックスは外部ネットワーク不可（boj.or.jp へ到達できない）ため URL/
      フォーマットを live で確認できていない。運用環境（GitHub Actions 等）で確認し、
      必要なら CGPI_CSV_URL / parser を調整すること。フォーマット不一致時は明示的に
      raise して Actions ログで可視化する（後述 parse_cgpi）。

本スクリプトが期待する「正規化 CSV スキーマ」（コメント行 '#' は無視）:
    period,level,yoy_pct,release
    2025-06,128.0,3.1,final
    ...
    2026-05,134.5,6.3,flash      # 速報（preliminary）
日銀の生 CSV は metadata ヘッダ行が複数あり列構成も異なるため、live 取得時は
download_cgpi_csv() が返す生テキストを上記スキーマへ整形する想定。raw フォーマットが
未対応なら parse_cgpi が ValueError を raise する。

速報値 / 確報値: release 列で判別（flash=速報, final=確報）。日銀では直近月が速報、
以降の月次更新で確報に置き換わる。本ストアは release_type を自然キーに含め両方保持する。

CLI:
    python scripts/fetch_cgpi.py            # 直近 3 ヶ月のみ upsert（idempotent）
    python scripts/fetch_cgpi.py --full     # 24 ヶ月分 backfill
    python scripts/fetch_cgpi.py --source PATH   # ローカル CSV を使う（オフライン/テスト）
    （環境変数 CGPI_SOURCE_CSV でも source パスを指定可）

引用は事実情報（政府/中央銀行統計）のみで、派生集計として保持する。
"""

from __future__ import annotations

import argparse
import io
import os
import sys
from pathlib import Path

import pandas as pd

# scripts/ から実行されるため repo root を import パスに追加。
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from lib import macro_reference  # noqa: E402

SOURCE = "boj"
SERIES_ID = "cgpi_total"
CGPI_LANDING_PAGE = "https://www.boj.or.jp/statistics/pi/cgpi_release/index.htm/"
CGPI_CSV_URL = "https://www.boj.or.jp/statistics/pi/cgpi_release/cgpi2020.csv"

_RELEASE_MAP = {
    "flash": "flash", "p": "flash", "preliminary": "flash", "速報": "flash",
    "final": "final", "f": "final", "確報": "final", "": "final",
}


def download_cgpi_csv(url: str = CGPI_CSV_URL, *, timeout: float = 30.0) -> str:
    """日銀 CGPI CSV を取得して生テキストを返す。失敗時は raise（Actions ログで可視化）。"""
    import requests

    resp = requests.get(url, timeout=timeout, headers={"User-Agent": "JIN-macro-fetcher/0.1"})
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or "utf-8"
    return resp.text


def parse_cgpi(text: str) -> pd.DataFrame:
    """正規化 CSV テキストを period/level/yoy_pct/release_type の DataFrame に変換する。

    - '#' 始まりの行と空行（metadata ヘッダ）は無視。
    - 必須列 period, level, yoy_pct が無い、または月次行が無い場合は ValueError を raise。
    """
    lines = [ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    if not lines:
        raise ValueError(
            "CGPI parse: データ行が見つからない（metadata のみ？フォーマット変更の可能性）"
        )

    df = pd.read_csv(io.StringIO("\n".join(lines)))
    df.columns = [str(c).strip().lower() for c in df.columns]
    required = {"period", "level", "yoy_pct"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(
            f"CGPI parse: 必須列が欠落 {sorted(missing)}（日銀フォーマット変更の可能性。"
            f"URL={CGPI_CSV_URL} を確認）。検出列={list(df.columns)}"
        )

    if "release" not in df.columns:
        df["release"] = ""
    df["period"] = df["period"].astype(str).str.strip()
    if not df["period"].str.match(r"^\d{4}-\d{2}$").all():
        bad = df.loc[~df["period"].str.match(r"^\d{4}-\d{2}$"), "period"].tolist()
        raise ValueError(f"CGPI parse: period 形式不正（YYYY-MM 期待）: {bad[:5]}")

    df["level"] = pd.to_numeric(df["level"], errors="coerce")
    df["yoy_pct"] = pd.to_numeric(df["yoy_pct"], errors="coerce")
    df["release_type"] = (
        df["release"].astype(str).str.strip().str.lower().map(_RELEASE_MAP).fillna("final")
    )
    df = df.dropna(subset=["level", "yoy_pct"])
    if df.empty:
        raise ValueError("CGPI parse: 数値化できる月次行が無い（フォーマット変更の可能性）")
    return df[["period", "level", "yoy_pct", "release_type"]].sort_values("period").reset_index(
        drop=True
    )


def to_rows(parsed: pd.DataFrame) -> pd.DataFrame:
    """parse 済み（period/level/yoy_pct/release_type）を macro_reference の行形式に展開する。"""
    fetched = macro_reference.now_iso()
    records = []
    for _, r in parsed.iterrows():
        common = {
            "source": SOURCE,
            "series_id": SERIES_ID,
            "period": r["period"],
            "release_type": r["release_type"],
            "fetched_at": fetched,
        }
        records.append({**common, "metric": "level", "value": float(r["level"])})
        records.append({**common, "metric": "yoy_pct", "value": float(r["yoy_pct"])})
    return pd.DataFrame(records, columns=macro_reference.COLUMNS)


def _load_source_text(source_arg: str | None) -> str:
    """source テキストを取得。優先: --source > env CGPI_SOURCE_CSV > live URL。"""
    path = source_arg or os.environ.get("CGPI_SOURCE_CSV")
    if path:
        return Path(path).read_text(encoding="utf-8")
    return download_cgpi_csv()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="日銀 CGPI（総合）月次を取得し parquet に upsert")
    parser.add_argument("--full", action="store_true", help="24ヶ月 backfill（既定 直近3ヶ月）")
    parser.add_argument("--source", default=None, help="ローカル CSV パス（オフライン/テスト用）")
    parser.add_argument("--months", type=int, default=3, help="既定取得月数（--full 未指定時）")
    args = parser.parse_args(argv)

    text = _load_source_text(args.source)
    parsed = parse_cgpi(text)

    if not args.full:
        parsed = parsed.tail(args.months)

    rows = to_rows(parsed)
    total = macro_reference.upsert(rows)
    months = sorted(parsed["period"].tolist())
    print(
        f"CGPI upsert: {len(rows)} rows ({len(parsed)} months "
        f"{months[0]}..{months[-1]}) -> total {total} rows in {macro_reference.PARQUET_PATH}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
