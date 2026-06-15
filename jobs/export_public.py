"""配信用 JSON エクスポータ（osd の x402 endpoint が読む jin_public.json を吐く）。

責務分離: 指数の計算は本リポジトリ（index_engine / jobs.daily）の責務。配信（x402 課金・
HTTP）は別リポジトリ（onchain-stock-data, osd）の責務。本モジュールは確定済みの観測値を
osd が「データとして」読める 1 ファイル（data/jin_public.json）に書き出すだけ。新しい
推論・予測ロジックは作らない。

ガードレール（§0 と同趣旨）:
- これは観測であって予測ではない。probability / forecast / 「上がりそう」の類は一切入れない。
- 返すのは観測値（excl/incl）+ matched SKU 数 + 方法論 + movers（その日動いた品目）+
  upstream CGPI（観測値）+ source / timestamp。
- coverage_note（単一店舗・代表性限定）を必ず含める。誇張しない。

スキーマ（jin_public.json）:
    {
      "source", "base_date", "generated_at",
      "methodology", "coverage_note", "license",
      "latest": {... 最新観測日 ...},
      "series": [{date, excl, incl, m_excl, m_incl}, ...],
      "movers_by_date": {"YYYY-MM-DD": [{category, item, pct, promo_tag, note}, ...]}
    }
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
from sqlmodel import select

from storage.db import get_session, get_settings
from storage.models import FoodClean, IndexValue

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = REPO_ROOT / "data" / "jin_public.json"

SOURCE = "japan-inflation-nowcast"
LICENSE = "observation data; derived aggregates only; see repo"
METHODOLOGY = (
    "Jevons elementary (matched-SKU geometric mean) + 10-category equal-weight upper "
    "aggregation; excl_promo removes SKUs flagged promo on base or current day; unit prices "
    "canonicalized (¥/100g, ¥/100ml, ¥/unit); base_date fixed."
)
COVERAGE_NOTE = (
    "single store, Tokyo metro delivery area, mid-tier supermarket (Life). "
    "Not nationally representative."
)
_MOVER_EPS = 0.05  # |pct| この値未満は据え置き扱いで mover に含めない


def _round(x: float | None, n: int = 2) -> float | None:
    return round(float(x), n) if x is not None and pd.notna(x) else None


def _series_and_latest(session: Any) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """index_values から excl/incl の時系列と最新観測を組み立てる。"""
    rows = session.exec(
        select(IndexValue).where(IndexValue.index_code == "JP-INFL-FOOD")
    ).all()
    by_date: dict[date, dict[str, Any]] = {}
    base_date = None
    for r in rows:
        d = r.date
        base_date = r.base_date
        slot = by_date.setdefault(d, {})
        if r.series_type == "food_excl_promo":
            slot["excl"] = r.value
            slot["m_excl"] = r.n
        elif r.series_type == "food_incl_promo":
            slot["incl"] = r.value
            slot["m_incl"] = r.n

    series: list[dict[str, Any]] = []
    for d in sorted(by_date):
        s = by_date[d]
        is_base = base_date is not None and d == base_date
        series.append(
            {
                "date": d.isoformat(),
                "excl": _round(s.get("excl")),
                "incl": _round(s.get("incl")),
                # base 日は matched 概念が自明（自分自身）なので null。
                "m_excl": None if is_base else s.get("m_excl"),
                "m_incl": None if is_base else s.get("m_incl"),
            }
        )
    latest = None
    if series:
        last_d = max(by_date)
        s = by_date[last_d]
        latest = {
            "as_of": last_d.isoformat(),
            "index": {"excl_promo": _round(s.get("excl")), "incl_promo": _round(s.get("incl"))},
            "matched_sku": {"excl": s.get("m_excl"), "incl": s.get("m_incl")},
        }
    return series, latest


def _cgpi_upstream() -> dict[str, Any]:
    """macro_reference parquet から観測済み CGPI YoY を引く（無ければ null）。"""
    try:
        from lib.macro_reference import get_latest_value

        v = get_latest_value("cgpi_total", "yoy_pct")
    except Exception:  # noqa: BLE001  参照系列が無くても本体は出す
        v = None
    if not v:
        return {"cgpi_yoy_pct": None, "cgpi_as_of": None}
    return {"cgpi_yoy_pct": v["value"], "cgpi_as_of": v["period"].isoformat()}


def _food_panel(session: Any) -> pd.DataFrame:
    rows = session.exec(select(FoodClean)).all()
    return pd.DataFrame(
        [
            {
                "scrape_date": r.scrape_date,
                "sku_key": r.sku_key,
                "unit_price": r.unit_price,
                "is_promo": bool(r.is_promo),
                "category": r.category,
                "product_name": r.product_name,
            }
            for r in rows
        ]
    )


def _movers_by_date(panel: pd.DataFrame, base_date: date) -> dict[str, list[dict[str, Any]]]:
    """各観測日について、基準日比で動いた SKU を変化率順に列挙する（観測事実のみ）。"""
    if panel.empty:
        return {}
    df = panel.copy()
    df["unit_price"] = pd.to_numeric(df["unit_price"], errors="coerce")
    df = df[df["unit_price"] > 0]
    # (sku, date) 中央単価のピボット。
    piv = df.groupby(["sku_key", "scrape_date"])["unit_price"].median().unstack("scrape_date")
    promo = df.groupby(["sku_key", "scrape_date"])["is_promo"].max().unstack("scrape_date")
    names = df.groupby("sku_key")["product_name"].last()
    cats = df.groupby("sku_key")["category"].last()

    if base_date not in piv.columns:
        return {}
    base = piv[base_date]
    dates = sorted([d for d in piv.columns if d != base_date])

    out: dict[str, list[dict[str, Any]]] = {}
    for d in dates:
        movers = []
        for sku in piv.index:
            b = base.get(sku)
            cur = piv.at[sku, d]
            if pd.isna(b) or pd.isna(cur) or b <= 0:
                continue
            pct = (cur / b - 1.0) * 100.0
            if abs(pct) < _MOVER_EPS:
                continue
            movers.append(
                {
                    "category": cats.get(sku),
                    "item": names.get(sku),
                    "pct": round(float(pct), 1),
                    "promo_tag": bool(promo.at[sku, d]) if not pd.isna(promo.at[sku, d]) else False,
                    "note": _days_at_level(piv.loc[sku], d),
                }
            )
        movers.sort(key=lambda m: abs(m["pct"]), reverse=True)
        out[d.isoformat()] = movers
    return out


def _days_at_level(sku_series: pd.Series, d: date) -> str:
    """sku のその日の単価が、直近何日連続で同水準かを観測事実として記す。"""
    s = sku_series.dropna()
    ordered = sorted(s.index)
    if d not in ordered:
        return ""
    cur = s[d]
    count = 0
    for dd in reversed([x for x in ordered if x <= d]):
        if abs(float(s[dd]) - float(cur)) < 1e-9:
            count += 1
        else:
            break
    return f"{count} day(s) at this level"


def build_public_payload(session: Any, *, base_date: date | None = None) -> dict[str, Any]:
    """配信用ペイロード（観測値のみ・予測なし）を組み立てる。"""
    series, latest = _series_and_latest(session)
    panel = _food_panel(session)
    if base_date is None:
        base_date = get_settings().base_date

    movers = _movers_by_date(panel, base_date)
    if latest is not None:
        latest = {
            "source": SOURCE,
            "as_of": latest["as_of"],
            "base_date": base_date.isoformat(),
            "index": latest["index"],
            "matched_sku": latest["matched_sku"],
            "upstream": _cgpi_upstream(),
            "methodology": METHODOLOGY,
            "coverage_note": COVERAGE_NOTE,
            "license": LICENSE,
        }

    return {
        "source": SOURCE,
        "base_date": base_date.isoformat(),
        "generated_at": datetime.now(UTC).isoformat(),
        "methodology": METHODOLOGY,
        "coverage_note": COVERAGE_NOTE,
        "license": LICENSE,
        "latest": latest,
        "series": series,
        "movers_by_date": movers,
    }


def write_public_json(path: Path = DEFAULT_OUT, *, base_date: date | None = None) -> dict[str, Any]:
    """jin_public.json を書き出す。書いたペイロードを返す。"""
    with get_session() as session:
        payload = build_public_payload(session, base_date=base_date)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="配信用 jin_public.json を書き出す（観測値のみ）")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="出力パス")
    args = parser.parse_args(argv)
    payload = write_public_json(Path(args.out))
    n_series = len(payload["series"])
    n_mv = sum(len(v) for v in payload["movers_by_date"].values())
    print(f"jin_public.json written: {n_series} series rows, {n_mv} movers -> {args.out}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
