"""日本銀行「企業物価指数（CGPI）」国内企業物価指数・総平均の月次 fetcher。

検証済みデータソース（2026-06-11 確認）:

  ソース A（primary）: 日銀 主要時系列統計データ表（HTML）
    URL: https://www.stat-search.boj.or.jp/ssi/mtshtml/pr01_m_1_en.html （英語・UTF-8、既定）
         https://www.stat-search.boj.or.jp/ssi/mtshtml/pr01_m_1.html （日本語・Shift-JIS）
    日本語版は Shift-JIS で文字化けし parse が落ちるため、UTF-8 の英語版を使う。系列コードは同一。
    認証不要・静的 URL。公表日当日に更新。単一の HTML テーブルで、ヘッダ部に
    「Name of time-series / Series code / Unit / Start / End / Last update」のメタ行が
    縦に並び、その下に YYYY/MM 行ラベルの月次データが続く。欠損は文字列 "ND"。
    level と yoy_pct の両方が日銀側で計算済みの列として取得できる（自前計算不要）。
    必要な系列コード:
      国内企業物価指数 総平均 (2020=100):      PR01'PRCG20_2200000000
      国内企業物価指数 総平均 前年比 (%):      PR01'PRCG20_2200000000%

  ソース B（未確認・--source bulk）: 一括ダウンロード zip
    URL: https://www.stat-search.boj.or.jp/info/cgpi_m_jp.zip
    公表日 10:00 頃までに更新。zip 内 CSV のフォーマットは **実物未確認**。
    データコードは検索サイトのコードから接頭辞 PR01' を除いたもの（例 PRCG20_2200000000）。
    エンコーディングは Shift-JIS の可能性が高い。→ 実装は NotImplementedError（TODO）。

注意: このサンドボックスは stat-search.boj.or.jp に到達できないため live 取得は未確認。
parse は検証済みの mtshtml テーブル構造を再現した fixture で検証する。live 確認は
GitHub Actions の workflow_dispatch で手動実行すること（docs/macro_reference.md 参照）。

改訂: 日銀は直近数ヶ月を訂正値(r)で遡及改訂する。本ストアは period を自然キーに含め、
再取得で同一 period の値を上書きする（lib.macro_reference.upsert）。

CLI:
    python scripts/fetch_cgpi.py                 # 直近3ヶ月のみ upsert（既定）
    python scripts/fetch_cgpi.py --full          # 24ヶ月 backfill
    python scripts/fetch_cgpi.py --source bulk    # 未実装（zip CSV）
    python scripts/fetch_cgpi.py --source PATH     # ローカル HTML（オフライン/テスト）
    （環境変数 CGPI_SOURCE_HTML でも HTML パスを指定可）
"""

from __future__ import annotations

import argparse
import io
import os
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from lib import macro_reference  # noqa: E402

SOURCE = "boj"
SERIES_ID = "cgpi_total"
RELEASE_TYPE = "mtshtml"  # 取得経路を release_type に記録（速報/確報の区別は日銀側で訂正値(r)管理）

MTSHTML_URL = "https://www.stat-search.boj.or.jp/ssi/mtshtml/pr01_m_1_en.html"
BULK_ZIP_URL = "https://www.stat-search.boj.or.jp/info/cgpi_m_jp.zip"

# 国内企業物価指数 総平均（2020=100）と前年比(%)の系列コード。
LEVEL_CODE = "PR01'PRCG20_2200000000"
YOY_CODE = "PR01'PRCG20_2200000000%"

_SERIES_CODE_LABELS = {"series code", "系列コード"}
_NULL_TOKENS = {"nd", "n.d.", "", "nan", "*", "-"}


def download_cgpi(url: str = MTSHTML_URL, *, timeout: float = 30.0) -> str:
    """日銀 mtshtml HTML を取得し文字列で返す。utf-8 失敗時は cp932 で再試行。

    失敗時は raise（GitHub Actions ログで可視化）。
    """
    import requests

    resp = requests.get(url, timeout=timeout, headers={"User-Agent": "JIN-macro-fetcher/0.1"})
    resp.raise_for_status()
    raw = resp.content
    for enc in ("utf-8", "cp932"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _norm_code(s: str) -> str:
    """系列コードの表記ズレを吸収（バックスラッシュ・半角/全角空白を除去）。

    日銀ページは "PR01'PRCG20\\_2200000000" のように `_` の前にバックスラッシュを置く。
    照合前に両辺を正規化して完全一致(==)で比べる。`%` は **除去しない**（level と yoy は
    `%` の有無だけが違うため）。
    """
    return s.replace("\\", "").replace(" ", "").replace("　", "").strip()


def _to_num(cell: object) -> float:
    """セル文字列を float に。"ND" 等の欠損トークンは NaN。"""
    s = str(cell).strip().replace(",", "")
    if s.lower() in _NULL_TOKENS:
        return float("nan")
    try:
        return float(s)
    except ValueError:
        return float("nan")


def parse_mtshtml_table(html: str) -> pd.DataFrame:
    """mtshtml HTML テーブルを period(date 月初日)/level/yoy_pct の DataFrame に変換する。

    - "Series code" 行から列→系列コードの対応を作り、LEVEL_CODE / YOY_CODE の列を特定。
    - YYYY/MM 行ラベルの月次行を抽出。"ND" は NaN。
    フォーマット不一致（Series code 行や対象コード列が無い等）は ValueError を raise。
    """
    try:
        tables = pd.read_html(io.StringIO(html), header=None)
    except ValueError as exc:  # テーブルが見つからない等
        raise ValueError(f"CGPI parse: HTML テーブルを検出できない: {exc}") from exc

    for raw in tables:
        df = raw.astype(str)
        # "Series code" 行を探す（列0にラベル）。
        code_row_idx = None
        for i in range(len(df)):
            if str(df.iat[i, 0]).strip().lower() in _SERIES_CODE_LABELS:
                code_row_idx = i
                break
        if code_row_idx is None:
            continue

        codes = {_norm_code(str(df.iat[code_row_idx, c])): c for c in range(df.shape[1])}
        if _norm_code(LEVEL_CODE) not in codes or _norm_code(YOY_CODE) not in codes:
            continue
        level_col = codes[_norm_code(LEVEL_CODE)]
        yoy_col = codes[_norm_code(YOY_CODE)]

        records = []
        for i in range(len(df)):
            label = str(df.iat[i, 0]).strip()
            if not pd.Series([label]).str.match(r"^\d{4}/\d{1,2}$").iat[0]:
                continue
            period = pd.to_datetime(label, format="%Y/%m").normalize()
            records.append(
                {
                    "period": period,
                    "level": _to_num(df.iat[i, level_col]),
                    "yoy_pct": _to_num(df.iat[i, yoy_col]),
                }
            )
        if not records:
            raise ValueError("CGPI parse: YYYY/MM 月次行が見つからない（フォーマット変更の可能性）")
        out = pd.DataFrame(records).sort_values("period").reset_index(drop=True)
        # level も yoy も NaN の行は捨てる。
        out = out.dropna(subset=["level", "yoy_pct"], how="all").reset_index(drop=True)
        if out.empty:
            raise ValueError("CGPI parse: 有効な月次データが無い")
        return out

    raise ValueError(
        "CGPI parse: 対象テーブル/系列コードが見つからない（日銀フォーマット変更の可能性。"
        f"URL={MTSHTML_URL}、code={LEVEL_CODE} / {YOY_CODE} を確認）"
    )


def to_rows(parsed: pd.DataFrame) -> pd.DataFrame:
    """parse 済み（period/level/yoy_pct）を macro_reference の行形式に展開する。

    値が NaN の metric は記録しない（ND を skip）。
    """
    fetched = macro_reference.now_iso()
    records = []
    for _, r in parsed.iterrows():
        common = {
            "source": SOURCE,
            "series_id": SERIES_ID,
            "period": r["period"],
            "release_type": RELEASE_TYPE,
            "fetched_at": fetched,
        }
        if pd.notna(r["level"]):
            records.append({**common, "metric": "level", "value": float(r["level"])})
        if pd.notna(r["yoy_pct"]):
            records.append({**common, "metric": "yoy_pct", "value": float(r["yoy_pct"])})
    return pd.DataFrame(records, columns=macro_reference.COLUMNS)


def _load_source_html(source_arg: str | None) -> str:
    """HTML テキストを取得。優先: bulk(未実装) > --source PATH / env > live mtshtml。"""
    if source_arg == "bulk":
        raise NotImplementedError(
            "ソース B（一括 zip CSV）は未実装。zip 内 CSV フォーマットを実物確認してから実装する "
            f"(URL={BULK_ZIP_URL}, encoding は Shift-JIS の可能性)。当面 mtshtml を使うこと。"
        )
    path = os.environ.get("CGPI_SOURCE_HTML")
    if not path and source_arg and source_arg != "mtshtml":
        path = source_arg
    if path:
        return Path(path).read_text(encoding="utf-8")
    return download_cgpi(MTSHTML_URL)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="日銀 CGPI（国内総平均）月次を parquet に upsert")
    parser.add_argument("--full", action="store_true", help="24ヶ月 backfill（既定 直近3ヶ月）")
    parser.add_argument(
        "--source", default="mtshtml", help="mtshtml（既定）/ bulk（未実装）/ ローカル HTML パス"
    )
    parser.add_argument("--months", type=int, default=3, help="既定取得月数（--full 未指定時）")
    args = parser.parse_args(argv)

    html = _load_source_html(args.source)
    parsed = parse_mtshtml_table(html)

    if not args.full:
        parsed = parsed.tail(args.months)

    rows = to_rows(parsed)
    total = macro_reference.upsert(rows)
    periods = parsed["period"].dt.strftime("%Y-%m").tolist()
    print(
        f"CGPI upsert: {len(rows)} rows ({len(parsed)} months "
        f"{periods[0]}..{periods[-1]}) -> total {total} rows in {macro_reference.PARQUET_PATH}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
