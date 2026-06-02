"""日次ジョブ（§3, §9 Phase 7）。

単一エントリポイント。cron から叩く。流れ:
    scrape -> etl -> index -> composite -> validate

すべて冪等（同 as_of 再実行で二重計上しない, §3）。各ステージを try で包み、失敗は
log して可能な範囲で続行する（部分復旧）。``config/sources.yaml`` が空なら scrape 段は
何も取得しない安全既定（§8）。
"""

from __future__ import annotations

import argparse
import logging
import time
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
from sqlmodel import select

from etl import food as etl_food
from etl import housing as etl_housing
from index_engine import composite, flow, food, hedonic, laspeyres
from methodology.generate import CURRENT_VERSION, record_version, write_methodology
from scrapers.base import SourceConfig, load_sources
from scrapers.food import ExampleFoodScraper
from scrapers.food.csv_import import CsvFoodImporter
from scrapers.housing import ExampleHousingScraper
from scrapers.housing.csv_import import CsvHousingImporter
from storage.db import get_session, get_settings, init_db
from storage.models import FoodClean, IndexValue, ListingClean

logger = logging.getLogger("jobs.daily")

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"

# 運用者が登録するアダプタ表。type='csv' は "csv" キー、それ以外は source.id で解決。
# 既定は参照アダプタ + CSV インポータのみ。実サイト向けは運用者が追加する（§8）。
HOUSING_ADAPTERS = {"example": ExampleHousingScraper, "csv": CsvHousingImporter}
FOOD_ADAPTERS = {"example": ExampleFoodScraper, "csv": CsvFoodImporter}


def _resolve_adapter(adapters: dict, src: SourceConfig):
    """type='csv' なら CSV インポータ、それ以外は source.id でアダプタを解決する。"""
    if src.type == "csv":
        return adapters.get("csv")
    return adapters.get(src.id)

NOWCAST = "JP-INFL-NOWCAST"
FOOD_CODE = "JP-INFL-FOOD"
HOUSING_CODE = "JP-INFL-HOUSING"
BASE_VALUE = 100.0


# --------------------------------------------------------------------------- #
# ステージ実行ヘルパ（時間と件数を log・例外は呼び出し側で握る）
# --------------------------------------------------------------------------- #
class _Stage:
    def __init__(self, name: str) -> None:
        self.name = name
        self.t0 = 0.0

    def __enter__(self) -> _Stage:
        self.t0 = time.monotonic()
        logger.info("stage start: %s", self.name)
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        dt = time.monotonic() - self.t0
        if exc is None:
            logger.info("stage ok: %s (%.3fs)", self.name, dt)
        else:
            logger.warning("stage failed: %s (%.3fs): %s", self.name, dt, exc)
        return True  # 例外を握りつぶして部分復旧する


# --------------------------------------------------------------------------- #
# scrape
# --------------------------------------------------------------------------- #
def _scrape(as_of: date) -> int:
    """config/sources.yaml の enabled ソースを取得し raw に upsert。空なら何もしない（§8）。"""
    s = get_settings()
    total = 0
    for src in load_sources("housing"):
        cls = _resolve_adapter(HOUSING_ADAPTERS, src)
        if cls is None:
            logger.warning("no housing adapter for source '%s' (type=%s); skip", src.id, src.type)
            continue
        adapter = cls(src, user_agent=s.scraper_user_agent, contact=s.scraper_contact)
        records = adapter.run()
        total += etl_housing.upsert_raw(records, scrape_date=as_of)
    for src in load_sources("food"):
        cls = _resolve_adapter(FOOD_ADAPTERS, src)
        if cls is None:
            logger.warning("no food adapter for source '%s' (type=%s); skip", src.id, src.type)
            continue
        adapter = cls(src, user_agent=s.scraper_user_agent, contact=s.scraper_contact)
        records = adapter.run()
        total += etl_food.upsert_raw(records, scrape_date=as_of)
    logger.info("scrape: %d raw records", total)
    return total


# --------------------------------------------------------------------------- #
# index 保存ヘルパ
# --------------------------------------------------------------------------- #
def _persist_index(session, value: dict[str, Any]) -> None:
    """index_values へ冪等保存（同一 index_code/date/series_type を置換）。"""
    code = value["index_code"]
    d = value["date"]
    series_type = value.get("series_type", "component")
    for old in session.exec(
        select(IndexValue).where(
            IndexValue.index_code == code,
            IndexValue.date == d,
            IndexValue.series_type == series_type,
        )
    ).all():
        session.delete(old)

    session.add(
        IndexValue(
            index_code=code,
            date=d,
            freq=value.get("freq", "D"),
            value=float(value["value"]),
            base_value=value.get("base_value"),
            base_date=value.get("base_date"),
            yoy_pct=value.get("yoy_pct"),
            mom_pct=value.get("mom_pct"),
            wow_pct=value.get("wow_pct"),
            n=value.get("n"),
            n_new=value.get("n_new"),
            series_type=series_type,
            coverage_pct=value.get("coverage_pct"),
            promo_mode=value.get("promo_mode"),
            components=value.get("components"),
            smoothing_window_days=value.get("smoothing_window_days"),
            methodology_version=value.get("methodology_version") or CURRENT_VERSION,
        )
    )


def _clean_df(session, model) -> pd.DataFrame:
    rows = session.exec(select(model)).all()
    records = [r.model_dump() for r in rows]
    df = pd.DataFrame(records)
    if not df.empty and "scrape_date" in df.columns:
        df["date"] = df["scrape_date"]
    return df


# --------------------------------------------------------------------------- #
# index（住居 + 食料）
# --------------------------------------------------------------------------- #
def _build_indices(session, *, as_of: date, base_date: date) -> dict[str, float]:
    """住居（hedonic/laspeyres/flow）と食料を計算し index_values に保存。

    Returns: composite 用のコンポーネント値 {code: value}（成功したものだけ）。
    """
    components: dict[str, float] = {}

    # --- 住居 ---
    housing_df = _clean_df(session, ListingClean)
    if not housing_df.empty:
        try:
            hed = hedonic.compute(
                housing_df, as_of=as_of, base_value=BASE_VALUE, base_date=base_date
            )
            hed["methodology_version"] = CURRENT_VERSION
            _persist_index(session, hed)
            components[HOUSING_CODE] = hed["value"]
        except Exception as exc:  # noqa: BLE001
            logger.warning("housing hedonic failed: %s", exc)

        try:
            base_win = housing_df[pd.to_datetime(housing_df["date"]).dt.date <= base_date]
            base_cells, weights = laspeyres.stratify(base_win)
            las = laspeyres.compute(
                housing_df, as_of=as_of, base_cells=base_cells, weights=weights,
                base_date=base_date, base_value=BASE_VALUE,
            )
            las["methodology_version"] = CURRENT_VERSION
            _persist_index(session, las)
        except Exception as exc:  # noqa: BLE001
            logger.warning("housing laspeyres failed: %s", exc)

        try:
            fl = flow.compute(housing_df, as_of=as_of, base_value=BASE_VALUE, base_date=base_date)
            fl["methodology_version"] = CURRENT_VERSION
            if fl["value"] == fl["value"]:  # NaN ガード
                _persist_index(session, fl)
        except Exception as exc:  # noqa: BLE001
            logger.warning("housing flow failed: %s", exc)

    # --- 食料 ---
    food_df = _clean_df(session, FoodClean)
    if not food_df.empty:
        try:
            fd = food.compute(
                food_df, as_of=as_of, base_date=base_date, base_value=BASE_VALUE,
                methodology_version=CURRENT_VERSION,
            )
            _persist_index(session, fd)
            components[FOOD_CODE] = fd["value"]
        except Exception as exc:  # noqa: BLE001
            logger.warning("food index failed: %s", exc)

    session.commit()
    return components


# --------------------------------------------------------------------------- #
# composite
# --------------------------------------------------------------------------- #
def _composite_weights() -> dict[str, float]:
    import yaml

    data = yaml.safe_load((CONFIG_DIR / "baskets.yaml").read_text(encoding="utf-8")) or {}
    return {k: float(v) for k, v in (data.get("composite_weights") or {}).items()}


def _build_composite(
    session, *, as_of: date, base_date: date, components: dict[str, float]
) -> None:
    if not components:
        logger.warning("composite skipped: no component values")
        return
    comps = [{"index_code": code, "value": val} for code, val in components.items()]
    result = composite.compose(
        comps, weights=_composite_weights(), base_date=base_date, base_value=BASE_VALUE,
        methodology_version=CURRENT_VERSION, as_of=as_of,
    )
    _persist_index(session, result)
    session.commit()


# --------------------------------------------------------------------------- #
# orchestrator
# --------------------------------------------------------------------------- #
def run(
    *,
    as_of: date | None = None,
    methodology_path: Path | None = None,
    official_csv: str | Path | None = None,
) -> int:
    """全段を順に実行する。Returns: プロセス終了コード（0=成功, 部分失敗でも 0）。"""
    as_of = as_of or date.today()
    base_date = get_settings().base_date
    init_db()
    logger.info("daily run start: as_of=%s base_date=%s", as_of, base_date)

    with _Stage("scrape"):
        _scrape(as_of)

    with _Stage("etl"):
        etl_housing.run(scrape_date=as_of)
        etl_food.run(scrape_date=as_of)

    components: dict[str, float] = {}
    with _Stage("index"), get_session() as session:
        components = _build_indices(session, as_of=as_of, base_date=base_date)

    with _Stage("composite"), get_session() as session:
        _build_composite(session, as_of=as_of, base_date=base_date, components=components)

    with _Stage("methodology"):
        write_methodology(methodology_path) if methodology_path else write_methodology()
        with get_session() as session:
            record_version(session)

    with _Stage("validate"):
        if official_csv:
            report = _validate(official_csv)
            logger.info("validation:\n%s", report.get("text", ""))

    logger.info("daily run done: as_of=%s components=%s", as_of, sorted(components))
    return 0


def _validate(official_csv: str | Path) -> dict[str, Any]:
    """index_values の headline 系列を読み、公式 CSV と YoY 比較する。"""
    from jobs.validate import run_from_csv

    computed: dict[str, pd.DataFrame] = {}
    headline = {NOWCAST: "composite_partial", FOOD_CODE: None, HOUSING_CODE: "stock_hedonic"}
    with get_session() as session:
        for code, stype in headline.items():
            q = select(IndexValue).where(IndexValue.index_code == code)
            if stype is not None:
                q = q.where(IndexValue.series_type == stype)
            rows = session.exec(q).all()
            if rows:
                computed[code] = pd.DataFrame(
                    {"date": [r.date for r in rows], "value": [r.value for r in rows]}
                )
    return run_from_csv(computed, official_csv)


def main() -> int:
    """CLI エントリポイント（pyproject の jin-daily）。"""
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    parser = argparse.ArgumentParser(description="Japan Inflation Nowcast daily job")
    parser.add_argument("--date", type=date.fromisoformat, default=None, help="対象日 (ISO)")
    parser.add_argument("--official-csv", default=None, help="検証用 公式系列 CSV パス")
    args = parser.parse_args()
    return run(as_of=args.date, official_csv=args.official_csv)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
