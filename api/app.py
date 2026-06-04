"""FastAPI アプリ（§7）。

無償/有償の境界（§7）:
- 無償: JP-INFL-NOWCAST の headline（latest + 直近 90 日 history）+ coverage_pct + disclaimer。
  /v1/indices と /v1/methodology も無償。
- x402 ゲート: /components / /wards / /bulk / incl-excl promo 切替 / 90 日超 history。

非交渉制約（§0）: レスポンス・docstring・description で「公式 CPI」「CPI そのもの」と
誤認させない。これは部分カバーのナウキャスト（速報）であり coverage_pct を必ず併記する。
"""

from __future__ import annotations

from datetime import date as Date  # 別名: フィールド名 `date` と型名の衝突を避ける
from datetime import datetime, timedelta
from typing import Any

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlmodel import select

from api.x402 import history_gate, payment_gate
from dashboard.render import build_headline_view, render_html
from storage.db import get_session
from storage.models import IndexValue

# §0 遵守: 「公式 CPI」と主張しない否定形の免責。これは速報（nowcast）である。
DISCLAIMER = (
    "This is an independent nowcast (速報), NOT official CPI. "
    "It covers only part of the CPI basket; see coverage_pct."
)

NOWCAST = "JP-INFL-NOWCAST"
FREE_HISTORY_DAYS = 90

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


_LATEST_EXAMPLE = {
    "index_code": NOWCAST,
    "date": "2025-06-01",
    "value": 103.2,
    "base_value": 100.0,
    "base_date": "2025-01-01",
    "series_type": "composite_partial",
    "coverage_pct": 47.13,
    "promo_mode": "excl_promo",
    "methodology_version": "v1",
    "disclaimer": DISCLAIMER,
}
_402_EXAMPLE = {
    "detail": {
        "error": "payment required",
        "payment_requirements": {
            "amount": "0.01",
            "asset": "usdc",
            "chain": "base",
            "recipient": "0x...",
            "facilitator_url": "https://facilitator.example",
            "resource": "components",
        },
    }
}


# --------------------------------------------------------------------------- #
# ヘルパ
# --------------------------------------------------------------------------- #
def _row_to_out(row: IndexValue) -> IndexValueOut:
    return IndexValueOut(
        index_code=row.index_code,
        date=row.date,
        freq=row.freq,
        value=row.value,
        base_value=row.base_value,
        base_date=row.base_date,
        yoy_pct=row.yoy_pct,
        mom_pct=row.mom_pct,
        wow_pct=row.wow_pct,
        n=row.n,
        n_new=row.n_new,
        series_type=row.series_type,
        coverage_pct=row.coverage_pct,
        promo_mode=row.promo_mode,
        components=row.components,
        smoothing_window_days=row.smoothing_window_days,
        methodology_version=row.methodology_version,
    )


def _latest_row(session, code: str) -> IndexValue | None:
    return session.exec(
        select(IndexValue).where(IndexValue.index_code == code).order_by(IndexValue.date.desc())
    ).first()


# --------------------------------------------------------------------------- #
# 無償ルート
# --------------------------------------------------------------------------- #
@app.get("/health")
def health() -> dict[str, str]:
    """ヘルスチェック。"""
    return {"status": "ok", "time": datetime.utcnow().isoformat()}


@app.get("/v1/indices")
def list_indices() -> list[dict[str, Any]]:
    """利用可能な指数コード一覧（§7）。無償。"""
    with get_session() as session:
        rows = session.exec(select(IndexValue)).all()
    latest: dict[str, IndexValue] = {}
    for r in rows:
        cur = latest.get(r.index_code)
        if cur is None or r.date >= cur.date:
            latest[r.index_code] = r
    return [
        {
            "index_code": code,
            "series_type": r.series_type,
            "latest_date": r.date.isoformat(),
            "coverage_pct": r.coverage_pct,
            "disclaimer": DISCLAIMER,
        }
        for code, r in sorted(latest.items())
    ]


@app.get(
    "/v1/indices/{code}/latest",
    response_model=IndexValueOut,
    responses={200: {"content": {"application/json": {"example": _LATEST_EXAMPLE}}}},
)
def latest(code: str) -> Any:
    """最新値（§7）。NOWCAST headline は無償（coverage_pct + disclaimer を含む）。"""
    with get_session() as session:
        row = _latest_row(session, code)
    if row is None:
        raise HTTPException(status_code=404, detail=f"unknown index_code: {code}")
    return _row_to_out(row)


@app.get(
    "/v1/indices/{code}/history",
    response_model=list[IndexValueOut],
    responses={
        200: {"content": {"application/json": {"example": [_LATEST_EXAMPLE]}}},
        402: {"content": {"application/json": {"example": _402_EXAMPLE}}},
    },
)
def history(code: str, days: int = 90, _gate: None = Depends(history_gate())) -> Any:
    """履歴（§7）。NOWCAST は直近 90 日まで無償、90 日超は x402 ゲート。"""
    with get_session() as session:
        rows = session.exec(
            select(IndexValue).where(IndexValue.index_code == code).order_by(IndexValue.date)
        ).all()
    if not rows:
        raise HTTPException(status_code=404, detail=f"unknown index_code: {code}")
    cutoff = max(r.date for r in rows) - timedelta(days=days)
    return [_row_to_out(r) for r in rows if r.date > cutoff]


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard() -> str:
    """無償 headline ダッシュボード（読み取り専用, §1）。NOWCAST の最新値 + 直近 90 日。

    §0 遵守: 部分カバーのナウキャスト（速報）であること・coverage_pct を画面に明示。
    """
    with get_session() as session:
        latest_row = _latest_row(session, NOWCAST)
        rows = session.exec(
            select(IndexValue)
            .where(IndexValue.index_code == NOWCAST)
            .order_by(IndexValue.date)
        ).all()
    if latest_row is None:
        return "<html><body><p>no data yet</p></body></html>"
    cutoff = max(r.date for r in rows) - timedelta(days=FREE_HISTORY_DAYS)
    history = [_row_to_out(r).model_dump(mode="json") for r in rows if r.date > cutoff]
    view = build_headline_view(_row_to_out(latest_row).model_dump(mode="json"), history)
    return render_html(view)


@app.get("/v1/methodology")
def methodology() -> dict[str, Any]:
    """公開方法論（§7）。無償。構造化メタ + 免責を返す（生 md は返さない）。"""
    return {
        "index_codes": [NOWCAST, "JP-INFL-FOOD", "JP-INFL-HOUSING"],
        "summary": (
            "独立系の物価ナウキャスト（速報）。食料 + 住居の部分カバー指数。"
            "住居はヘドニック + 代表バスケット、食料は Jevons + 上位ラスパイレス。"
        ),
        "methodology_url": "/methodology/methodology.md",
        "disclaimer": DISCLAIMER,
    }


# --------------------------------------------------------------------------- #
# x402 ゲート対象ルート
# --------------------------------------------------------------------------- #
@app.get(
    "/v1/indices/{code}/components",
    responses={402: {"content": {"application/json": {"example": _402_EXAMPLE}}}},
)
def components(code: str, _gate: None = Depends(payment_gate("components"))) -> dict[str, Any]:
    """コンポーネント分解（§7）。x402 ゲート対象。"""
    with get_session() as session:
        row = _latest_row(session, code)
    if row is None:
        raise HTTPException(status_code=404, detail=f"unknown index_code: {code}")
    return {
        "index_code": code,
        "date": row.date.isoformat(),
        "value": row.value,
        "coverage_pct": row.coverage_pct,
        "components": row.components or [],
        "disclaimer": DISCLAIMER,
    }


@app.get(
    "/v1/indices/{code}/wards",
    responses={402: {"content": {"application/json": {"example": _402_EXAMPLE}}}},
)
def wards(code: str, _gate: None = Depends(payment_gate("wards"))) -> dict[str, Any]:
    """ward 別（§7）。x402 ゲート対象（ward 別系列は今後拡張）。"""
    return {"index_code": code, "wards": [], "disclaimer": DISCLAIMER}


@app.get(
    "/v1/indices/{code}/bulk",
    responses={402: {"content": {"application/json": {"example": [_LATEST_EXAMPLE]}}}},
)
def bulk(code: str, _gate: None = Depends(payment_gate("bulk"))) -> dict[str, Any]:
    """bulk 出力（§7）。x402 ゲート対象。全履歴を返す。"""
    with get_session() as session:
        rows = session.exec(
            select(IndexValue).where(IndexValue.index_code == code).order_by(IndexValue.date)
        ).all()
    return {
        "index_code": code,
        "count": len(rows),
        "series": [_row_to_out(r).model_dump(mode="json") for r in rows],
        "disclaimer": DISCLAIMER,
    }
