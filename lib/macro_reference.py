"""マクロ参照系列ストア（data/macro_reference.parquet）。

公的月次統計（第一弾は日銀 CGPI）を JIN の日次系列と並べる reference として保持する。
parquet は .gitignore 配下（GitHub Actions が更新して PR で反映）。

スキーマ（columns）:
    source         : str       例 "boj"
    series_id      : str       例 "cgpi_total"
    period         : date       月初日（YYYY-MM-01）。月次の代表日。
    value          : float
    metric         : str       "level" | "yoy_pct"
    release_type   : str       取得経路/版（例 "mtshtml"）。日銀は直近月を遡及改訂(r)する
                               ため、同一自然キーの再取得で値が上書きされる設計。
    fetched_at     : str       ISO8601 UTC

自然キー: (source, series_id, period, metric, release_type)。upsert は同キーを置換する
（= 改訂値で上書き）。
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
PARQUET_PATH = REPO_ROOT / "data" / "macro_reference.parquet"

COLUMNS = ["source", "series_id", "period", "value", "metric", "release_type", "fetched_at"]
NATURAL_KEY = ["source", "series_id", "period", "metric", "release_type"]


def empty_frame() -> pd.DataFrame:
    """空のスキーマ DataFrame。"""
    df = pd.DataFrame({c: pd.Series(dtype="object") for c in COLUMNS})
    df["value"] = df["value"].astype("float64")
    df["period"] = pd.to_datetime(df["period"])  # datetime64[ns]
    return df


def _normalize_period(df: pd.DataFrame) -> pd.DataFrame:
    """period 列を月初日の datetime64 に正規化する。"""
    if "period" in df.columns:
        df["period"] = pd.to_datetime(df["period"]).dt.normalize()
    return df


def load(path: Path = PARQUET_PATH) -> pd.DataFrame:
    """parquet を読む。無ければ空スキーマを返す。"""
    if not Path(path).exists():
        return empty_frame()
    df = pd.read_parquet(path)
    # 列が欠けていても落ちないように整える。
    for c in COLUMNS:
        if c not in df.columns:
            df[c] = pd.NA
    return _normalize_period(df[COLUMNS])


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def upsert(rows: pd.DataFrame, *, path: Path = PARQUET_PATH) -> int:
    """rows を自然キーで upsert し parquet に書き戻す。Returns: 書き込み後の総行数。

    同一自然キーは新しい rows 側で置換（冪等: 同じ入力の再実行で行数は増えない）。
    """
    if rows.empty:
        existing = load(path)
        return len(existing)

    rows = rows.copy()
    for c in COLUMNS:
        if c not in rows.columns:
            raise ValueError(f"upsert: 必須カラム欠落 {c}")
    rows = _normalize_period(rows[COLUMNS])

    combined = pd.concat([load(path), rows], ignore_index=True)
    # 後勝ち（新しい rows を優先）で自然キー重複を排除。
    combined = combined.drop_duplicates(subset=NATURAL_KEY, keep="last").reset_index(drop=True)
    combined = combined.sort_values(["source", "series_id", "metric", "period"]).reset_index(
        drop=True
    )

    Path(path).parent.mkdir(parents=True, exist_ok=True)
    combined.to_parquet(path, index=False)
    return len(combined)


def get_latest_value(
    series_id: str, metric: str = "yoy_pct", *, path: Path = PARQUET_PATH
) -> dict[str, Any] | None:
    """指定 series_id / metric の最新 period の行を返す。無ければ None。

    最新判定は period の降順。同 period に flash/final が両方ある場合は
    fetched_at が新しい方（同点なら final 優先）を返す。
    """
    df = load(path)
    if df.empty:
        return None
    sub = df[(df["series_id"] == series_id) & (df["metric"] == metric)].copy()
    if sub.empty:
        return None
    sub = sub.sort_values(["period", "fetched_at"], ascending=[True, True])
    row = sub.iloc[-1]
    return {
        "source": row["source"],
        "series_id": row["series_id"],
        "period": pd.Timestamp(row["period"]).date(),
        "value": float(row["value"]),
        "metric": row["metric"],
        "release_type": row["release_type"],
        "fetched_at": row["fetched_at"],
    }
