"""Phase 7 受け入れ条件のテスト（daily 全段 + 検証 + methodology, §6-4, §9）。

実通信なし・決定的。一時 SQLite に合成 clean データを seed して daily.run を回す。
"""

from __future__ import annotations

import math
from datetime import date

import pandas as pd
import pytest
from sqlmodel import select

from storage.models import FoodClean, IndexValue, ListingClean, MethodologyVersion

BASE_DATE = date(2025, 1, 1)
AS_OF = date(2025, 3, 1)

# 住居ヘドニック面（無ノイズ）
WARDS = ["placeholder", "B"]
MADORI = {"1K": 25.0, "1LDK": 40.0, "2LDK": 55.0}
AGES = [1, 2]
WALKS = [0, 1]
FLOORS = [2, 3, 4, 5]
B0, B_LA, B_FLOOR = 10.0, 0.7, 0.01
WARD_EFF = {"placeholder": 0.0, "B": 0.10}
MAD_EFF = {"1K": 0.0, "1LDK": 0.15, "2LDK": 0.25}
AGE_EFF = {1: 0.0, 2: -0.05}
WALK_EFF = {0: 0.0, 1: -0.03}


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    db_path = tmp_path / "jin.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    import storage.db as db

    db.get_settings.cache_clear()
    db.get_engine.cache_clear()
    db.init_db()
    yield db
    db.get_settings.cache_clear()
    db.get_engine.cache_clear()


def _seed_housing(session, on: date, price_mult: float) -> None:
    n = 0
    for ward in WARDS:
        for madori, base_area in MADORI.items():
            for age in AGES:
                for walk in WALKS:
                    for floor in FLOORS:
                        area = base_area + floor * 0.5
                        ln = (
                            B0 + B_LA * math.log(area) + B_FLOOR * floor
                            + WARD_EFF[ward] + MAD_EFF[madori] + AGE_EFF[age] + WALK_EFF[walk]
                        )
                        rent = math.exp(ln) * price_mult
                        session.add(
                            ListingClean(
                                listing_id=f"H{on.isoformat()}-{n}", source="seed",
                                scrape_date=on, first_seen=on, last_seen=on, is_active=True,
                                ward=ward, madori=madori, structure="RC",
                                age_band=age, walk_band=walk, floor=floor, area_m2=area,
                                rent_total=rent, log_area=math.log(area),
                                rent_per_m2=rent / area,
                            )
                        )
                        n += 1


def _seed_food(session, on: date, price_mult: float) -> None:
    skus = [
        ("g1", 50.0, "穀類"), ("g2", 60.0, "穀類"),
        ("m1", 20.0, "乳卵類"), ("m2", 25.0, "乳卵類"),
    ]
    for sku, price, cat in skus:
        session.add(
            FoodClean(
                item_id=f"{sku}-{on.isoformat()}", source="seed", scrape_date=on,
                first_seen=on, last_seen=on, is_active=True, category=cat,
                product_name=sku, brand="brand", unit="g", unit_size=100.0,
                price=price * price_mult * 100.0, is_promo=False, in_stock=True,
                sku_key=sku, unit_price=price * price_mult,
            )
        )


def _seed_all(db) -> None:
    with db.get_session() as s:
        _seed_housing(s, BASE_DATE, 1.0)
        _seed_housing(s, AS_OF, 1.05)
        _seed_food(s, BASE_DATE, 1.0)
        _seed_food(s, AS_OF, 1.05)
        s.commit()


def _rows(db, **filt) -> list[IndexValue]:
    with db.get_session() as s:
        q = select(IndexValue)
        for k, v in filt.items():
            q = q.where(getattr(IndexValue, k) == v)
        return list(s.exec(q).all())


# --------------------------------------------------------------------------- #
# 1) daily.run が全段を実行
# --------------------------------------------------------------------------- #
def test_daily_run_builds_all_series(fresh_db, tmp_path) -> None:
    from jobs import daily

    _seed_all(fresh_db)
    rc = daily.run(as_of=AS_OF, methodology_path=tmp_path / "methodology.md")
    assert rc == 0

    nowcast = _rows(fresh_db, index_code="JP-INFL-NOWCAST", date=AS_OF)
    food = _rows(fresh_db, index_code="JP-INFL-FOOD", date=AS_OF)
    housing = _rows(fresh_db, index_code="JP-INFL-HOUSING", series_type="stock_hedonic")
    assert len(nowcast) == 1
    assert len(food) == 1
    assert len(housing) == 1

    # 合成は coverage_pct 付き（部分カバー, §0）。
    assert nowcast[0].coverage_pct is not None and nowcast[0].coverage_pct < 100.0
    assert nowcast[0].series_type == "composite_partial"
    # 食料・住居とも +5% を反映（homogeneity）。
    assert food[0].value == pytest.approx(105.0, rel=1e-6)
    assert housing[0].value == pytest.approx(105.0, rel=1e-6)


# --------------------------------------------------------------------------- #
# 2) 冪等性（同 as_of 2回で二重化なし）
# --------------------------------------------------------------------------- #
def test_daily_run_idempotent(fresh_db, tmp_path) -> None:
    from jobs import daily

    _seed_all(fresh_db)
    daily.run(as_of=AS_OF, methodology_path=tmp_path / "m.md")
    daily.run(as_of=AS_OF, methodology_path=tmp_path / "m.md")

    assert len(_rows(fresh_db, index_code="JP-INFL-NOWCAST", date=AS_OF)) == 1
    assert len(_rows(fresh_db, index_code="JP-INFL-FOOD", date=AS_OF)) == 1
    assert len(_rows(fresh_db, index_code="JP-INFL-HOUSING", series_type="stock_hedonic")) == 1


# --------------------------------------------------------------------------- #
# 3) 部分復旧（住居 hedonic を故意に失敗させても落ちず食料合成は進む）
# --------------------------------------------------------------------------- #
def test_daily_run_partial_recovery(fresh_db, tmp_path, monkeypatch) -> None:
    from jobs import daily

    _seed_all(fresh_db)

    def _boom(*a, **k):
        raise RuntimeError("forced hedonic failure")

    monkeypatch.setattr(daily.hedonic, "compute", _boom)
    rc = daily.run(as_of=AS_OF, methodology_path=tmp_path / "m.md")
    assert rc == 0  # 落ちない

    # 住居 hedonic は失敗 -> コンポーネント欠落。食料は出る。
    assert len(_rows(fresh_db, index_code="JP-INFL-HOUSING", series_type="stock_hedonic")) == 0
    assert len(_rows(fresh_db, index_code="JP-INFL-FOOD", date=AS_OF)) == 1
    # 合成は食料のみ -> coverage は食料分だけ（< 全体）。
    nowcast = _rows(fresh_db, index_code="JP-INFL-NOWCAST", date=AS_OF)
    assert len(nowcast) == 1
    assert nowcast[0].coverage_pct == pytest.approx(2626.0 / 10000.0 * 100.0)


# --------------------------------------------------------------------------- #
# 4) validation: 検証レポート生成
# --------------------------------------------------------------------------- #
def test_validation_report(tmp_path) -> None:
    from jobs import validate

    dates = pd.date_range("2024-01-01", "2025-06-01", freq="D")
    computed = {
        "JP-INFL-NOWCAST": pd.DataFrame(
            {"date": dates, "value": [100.0 * (1 + 0.03 * i / 365) for i in range(len(dates))]}
        )
    }
    # 公式 CSV（YoY ~2.5%）。
    csv = tmp_path / "official.csv"
    rows = [
        {"date": d.date().isoformat(), "code": "JP-INFL-NOWCAST",
         "value": 100.0 * (1 + 0.025 * i / 365)}
        for i, d in enumerate(dates)
    ]
    pd.DataFrame(rows).to_csv(csv, index=False)

    report = validate.run_from_csv(computed, csv)
    assert "text" in report and report["series"]
    s = report["series"][0]
    assert s["code"] == "JP-INFL-NOWCAST"
    assert s["n"] > 0
    assert s["mean_abs_dev_pp"] is not None
    assert s["direction_match_rate"] == pytest.approx(1.0)  # 両者とも上昇
    # 乖離は概ね 0.5pp 前後（3% vs 2.5%）。
    assert s["mean_abs_dev_pp"] < 1.0


# --------------------------------------------------------------------------- #
# 5) methodology 生成 + version 記録 + 公式CPI誤認なし
# --------------------------------------------------------------------------- #
def test_methodology_generation_and_version(fresh_db) -> None:
    from methodology import generate

    md = generate.build_methodology_md()
    for section in ("ナウキャスト", "ヘドニック", "Jevons", "ラスパイレス",
                    "coverage", "既知の限界", "バージョン履歴"):
        assert section in md
    # §0 遵守: 誤認表記が無い。
    for bad in ("公式 CPI", "公式CPI", "CPI そのもの", "CPIそのもの"):
        assert bad not in md
    # coverage は 100 未満で明記。
    assert "100 未満" in md

    with fresh_db.get_session() as s:
        generate.record_version(s)
        versions = list(s.exec(select(MethodologyVersion)).all())
    assert any(v.version == generate.CURRENT_VERSION for v in versions)
