"""配信用 jin_public.json エクスポータのテスト（観測値のみ・予測なし）。

実通信なし。committed fixtures（06-04, 06-05）で 2 日パネルを作り、payload を検証する。
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

FIX = Path(__file__).resolve().parent / "fixtures"
D04 = date(2026, 6, 4)
D05 = date(2026, 6, 5)
# 予測・確率系の語は payload に一切現れてはならない（ガードレール1）。
FORBIDDEN = ["probability", "forecast", "predict", "上がりそう", "下がりそう", "確率", "予測"]


@pytest.fixture
def seeded_db(tmp_path, monkeypatch):
    db_path = tmp_path / "jin.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("BASE_DATE", "2026-06-04")
    import storage.db as db

    db.get_settings.cache_clear()
    db.get_engine.cache_clear()
    db.init_db()

    from jobs import daily
    from jobs.import_csv import import_csv

    import_csv(str(FIX / "life_basket_20260604.csv"), scrape_date=D04, kind="food")
    import_csv(str(FIX / "life_basket_20260605.csv"), scrape_date=D05, kind="food")
    monkeypatch.setattr(daily, "load_sources", lambda kind: [])
    # 各日 index を計算（base 固定 06-04）。
    daily.run(as_of=D04, methodology_path=tmp_path / "m.md")
    daily.run(as_of=D05, methodology_path=tmp_path / "m.md")
    yield db
    db.get_settings.cache_clear()
    db.get_engine.cache_clear()


def _payload(db):
    from jobs.export_public import build_public_payload

    with db.get_session() as s:
        return build_public_payload(s, base_date=D04)


def test_schema_and_latest(seeded_db) -> None:
    p = _payload(seeded_db)
    assert p["source"] == "japan-inflation-nowcast"
    assert p["base_date"] == "2026-06-04"
    assert p["coverage_note"] and "single store" in p["coverage_note"]

    latest = p["latest"]
    assert latest["as_of"] == "2026-06-05"
    assert set(latest["index"]) == {"excl_promo", "incl_promo"}
    assert latest["index"]["excl_promo"] is not None
    assert set(latest["matched_sku"]) == {"excl", "incl"}
    # upstream は観測 CGPI（無ければ null）。キーは必ず存在。
    assert "upstream" in latest and "cgpi_yoy_pct" in latest["upstream"]
    assert latest["coverage_note"]  # 各レスポンスに必ず coverage_note


def test_series_base_row_has_null_matched(seeded_db) -> None:
    p = _payload(seeded_db)
    dates = [r["date"] for r in p["series"]]
    assert dates == ["2026-06-04", "2026-06-05"]
    base_row = p["series"][0]
    assert base_row["excl"] == 100.0 and base_row["incl"] == 100.0
    assert base_row["m_excl"] is None and base_row["m_incl"] is None  # base は null
    last = p["series"][-1]
    assert last["m_excl"] is not None and last["m_excl"] > 0


def test_movers_are_observation_only(seeded_db) -> None:
    p = _payload(seeded_db)
    mv = p["movers_by_date"].get("2026-06-05")
    assert mv is not None and len(mv) >= 1
    for m in mv:
        assert set(m) == {"category", "item", "pct", "promo_tag", "note"}
        assert isinstance(m["pct"], int | float)  # 観測の変化率（確率ではない）
        assert isinstance(m["promo_tag"], bool)
        assert "level" in m["note"]
    # ロイヤルブレッド 6枚 は base 171 -> 225 = +31.6% が観測されるはず。
    bread = [m for m in mv if "ロイヤルブレッド 6枚" in str(m["item"])]
    assert bread and bread[0]["pct"] == pytest.approx(31.6, abs=0.1)
    assert bread[0]["promo_tag"] is False


def test_no_forecast_language_anywhere(seeded_db) -> None:
    p = _payload(seeded_db)
    blob = json.dumps(p, ensure_ascii=False).lower()
    for bad in FORBIDDEN:
        assert bad.lower() not in blob


def test_write_public_json_roundtrip(seeded_db, tmp_path) -> None:
    from jobs.export_public import write_public_json

    out = tmp_path / "jin_public.json"
    write_public_json(out, base_date=D04)
    loaded = json.loads(out.read_text(encoding="utf-8"))
    assert loaded["latest"]["as_of"] == "2026-06-05"
    assert loaded["movers_by_date"]
