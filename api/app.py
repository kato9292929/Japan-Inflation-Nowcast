"""FastAPI アプリ（§7）。

無償/有償の境界（§7）:
- 無償: JP-INFL-NOWCAST の headline（latest + 直近 90 日）+ coverage_pct のみ。
- x402 ゲート: コンポーネント分解 / 中分類別 / ward 別 / incl-excl promo 切替 /
  90 日超 history / bulk。

非交渉制約（§0）: レスポンス・docstring・description で「公式 CPI」と誤認させない。
これは部分カバーのナウキャスト（速報）であり coverage_pct を必ず併記する。

Phase 0 はルート枠と値オブジェクトのみ。データ取得本体は Phase 6 で実装する。
"""

from __future__ import annotations

from datetime import date as Date  # 別名: フィールド名 `date` と型名の衝突を避ける
from datetime import datetime
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

# require_payment は Phase 6 で課金ルートの Depends に配線する（api/x402.py）。

DISCLAIMER = (
    "This is an independent nowcast (速報), NOT official CPI. "
    "It covers only part of the CPI basket; see coverage_pct."
)

app = FastAPI(
    title="Japan Inflation Nowcast API",
    version="0.0.0",
    description=DISCLAIMER,
)


class IndexValueOut(BaseModel):
    """§5 の index_values 値オブジェクトに対応する公開スキーマ。"""

    index_code: str
    date: Date
    freq: str = "D"
    value: float
    base_value: float | None = None
    base_date: Date
    yoy_pct: float | None = None
    mom_pct: float | None = None
    wow_pct: float | None = None
    n: int | None = None
    n_new: int | None = None
    series_type: str
    coverage_pct: float | None = Field(
        default=None, description="CPI バスケットのカバー率（合成で必須, §0）"
    )
    promo_mode: str | None = None
    components: list[dict[str, Any]] | None = None
    smoothing_window_days: int | None = None
    methodology_version: str
    disclaimer: str = DISCLAIMER


@app.get("/health")
def health() -> dict[str, str]:
    """ヘルスチェック。"""
    return {"status": "ok", "time": datetime.utcnow().isoformat()}


@app.get("/v1/indices")
def list_indices() -> list[dict[str, Any]]:
    """利用可能な指数コード一覧（§7）。無償。"""
    raise HTTPException(status_code=501, detail="Phase 6: 指数一覧を実装する")


@app.get("/v1/indices/{code}/latest", response_model=IndexValueOut)
def latest(code: str) -> Any:
    """最新値（§7）。NOWCAST headline は無償。"""
    raise HTTPException(status_code=501, detail="Phase 6: latest を実装する")


@app.get("/v1/indices/{code}/history")
def history(code: str, days: int = 90) -> list[IndexValueOut]:
    """履歴（§7）。NOWCAST は直近 90 日まで無償、超過は x402 ゲート。"""
    raise HTTPException(status_code=501, detail="Phase 6: history を実装する")


@app.get("/v1/indices/{code}/components")
def components(code: str) -> Any:
    """コンポーネント分解（§7）。x402 ゲート対象。"""
    raise HTTPException(status_code=501, detail="Phase 6: components を実装する（x402 ゲート）")


@app.get("/v1/indices/{code}/wards")
def wards(code: str) -> Any:
    """ward 別（§7）。x402 ゲート対象。"""
    raise HTTPException(status_code=501, detail="Phase 6: wards を実装する（x402 ゲート）")


@app.get("/v1/indices/{code}/bulk")
def bulk(code: str) -> Any:
    """bulk 出力（§7）。x402 ゲート対象。"""
    raise HTTPException(status_code=501, detail="Phase 6: bulk を実装する（x402 ゲート）")


@app.get("/v1/methodology")
def methodology() -> dict[str, Any]:
    """公開方法論（§7）。無償。"""
    raise HTTPException(status_code=501, detail="Phase 6: methodology を実装する")
