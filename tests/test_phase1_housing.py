"""Phase 1 受け入れ条件のテスト（住居スクレイパ + ETL, §6-1, §8）。

ネットワークに出ない（httpx クライアントは注入したフェイクを使う）。
DB は一時 SQLite（fresh_db フィクスチャ）。
"""

from __future__ import annotations

import math
from datetime import date
from pathlib import Path

import pytest
from sqlmodel import select

from etl import housing as etl_housing
from scrapers.base import BaseScraper, DisallowedPathError, SourceConfig
from scrapers.housing import ExampleHousingScraper
from storage.models import ListingClean, ListingRaw

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "housing_example.html"
DAY1 = date(2025, 1, 1)
DAY2 = date(2025, 1, 2)
REF_YEAR = 2025


# --------------------------------------------------------------------------- #
# フィクスチャ
# --------------------------------------------------------------------------- #
@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    """一時 SQLite を用意し、設定/エンジンキャッシュをクリアして init_db する。"""
    db_path = tmp_path / "jin.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    import storage.db as db

    db.get_settings.cache_clear()
    db.get_engine.cache_clear()
    db.init_db()
    yield db
    db.get_settings.cache_clear()
    db.get_engine.cache_clear()


def _source(**kw) -> SourceConfig:
    return SourceConfig(id="example", base_url="https://example.test", enabled=True, **kw)


def _scraper(**kw) -> ExampleHousingScraper:
    return ExampleHousingScraper(
        _source(**kw),
        user_agent="JapanInflationNowcastBot/test",
        contact="ops@example.com",
        sleeper=lambda _s: None,  # 実待機しない
    )


def _listing_record(listing_id: str, **fields) -> dict:
    base = {"source": "example", "listing_id": listing_id}
    base.update(fields)
    return base


# --------------------------------------------------------------------------- #
# 1) parse: HTML 契約からの抽出
# --------------------------------------------------------------------------- #
def test_parse_fixture_extracts_records() -> None:
    html = FIXTURE.read_text(encoding="utf-8")
    records = _scraper().parse(html, source_path="/list")

    # listing_id を持つ 3 件のみ（ID 無しノードはスキップ）。
    assert len(records) == 3

    by_id = {r["listing_id"]: r for r in records}
    l1 = by_id["L001"]
    assert l1["source"] == "example"
    assert l1["ward"] == "渋谷区"
    assert l1["station"] == "渋谷"
    assert l1["madori"] == "1K"
    assert l1["structure"] == "RC"
    assert l1["walk_min"] == 5.0
    assert l1["rent_total"] == 120000.0  # カンマ除去
    assert l1["mgmt_fee"] == 8000.0
    assert l1["area_m2"] == 25.5
    assert l1["build_year"] == 2010.0
    assert l1["floor"] == 3.0
    assert l1["raw_payload"]["rent_total"] == "120,000"


# --------------------------------------------------------------------------- #
# 2) pipeline: raw -> clean と特徴量
# --------------------------------------------------------------------------- #
def test_pipeline_builds_clean_with_features(fresh_db) -> None:
    html = FIXTURE.read_text(encoding="utf-8")
    records = _scraper().parse(html, source_path="/list")

    assert etl_housing.upsert_raw(records, scrape_date=DAY1) == 3
    assert etl_housing.run(scrape_date=DAY1, as_of_year=REF_YEAR) == 3

    with fresh_db.get_session() as s:
        clean = {r.listing_id: r for r in s.exec(select(ListingClean)).all()}

    assert set(clean) == {"L001", "L002", "L003"}
    l1 = clean["L001"]
    assert l1.log_area == pytest.approx(math.log(25.5))
    assert l1.rent_per_m2 == pytest.approx(120000.0 / 25.5)
    # age = 2025 - 2010 = 15 -> bounds [5,10,20,30] -> band 2
    assert l1.age_band == 2
    # walk_min = 5 -> bounds [5,10,15] -> band 1
    assert l1.walk_band == 1
    assert l1.scrape_date == DAY1
    assert l1.is_active is True


# --------------------------------------------------------------------------- #
# 3) 冪等性
# --------------------------------------------------------------------------- #
def test_idempotent_reruns_do_not_duplicate(fresh_db) -> None:
    html = FIXTURE.read_text(encoding="utf-8")
    records = _scraper().parse(html, source_path="/list")

    for _ in range(2):
        etl_housing.upsert_raw(records, scrape_date=DAY1)
        etl_housing.run(scrape_date=DAY1, as_of_year=REF_YEAR)

    with fresh_db.get_session() as s:
        n_raw = len(s.exec(select(ListingRaw)).all())
        n_clean = len(s.exec(select(ListingClean)).all())
    assert n_raw == 3
    assert n_clean == 3


# --------------------------------------------------------------------------- #
# 4) ライフサイクル（first_seen 保持 / last_seen 更新 / 市場退出）
# --------------------------------------------------------------------------- #
def test_lifecycle_first_last_seen_and_exit(fresh_db) -> None:
    day1 = [
        _listing_record("A", rent_total="100000", area_m2="25"),
        _listing_record("B", rent_total="150000", area_m2="30"),
        _listing_record("C", rent_total="200000", area_m2="40"),
    ]
    day2 = [
        _listing_record("A", rent_total="110000", area_m2="25"),
        _listing_record("B", rent_total="150000", area_m2="30"),
    ]

    etl_housing.upsert_raw(day1, scrape_date=DAY1)
    etl_housing.upsert_raw(day2, scrape_date=DAY2)

    with fresh_db.get_session() as s:
        rows = {r.listing_id: r for r in s.exec(select(ListingRaw)).all()}

    # C は day2 に現れず退出。
    assert rows["C"].is_active is False
    assert rows["C"].first_seen == DAY1
    # A/B は last_seen 更新・first_seen 保持・active 継続。
    for lid in ("A", "B"):
        assert rows[lid].is_active is True
        assert rows[lid].first_seen == DAY1
        assert rows[lid].last_seen == DAY2
    # A は値更新（rent_total 反映）。
    assert rows["A"].rent_total == 110000.0


# --------------------------------------------------------------------------- #
# 5) 遵守: robots 不許可パスは fetch しない（実通信なし）
# --------------------------------------------------------------------------- #
class _FakeResponse:
    def __init__(self, status_code: int, text: str) -> None:
        self.status_code = status_code
        self.text = text

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            import httpx

            raise httpx.HTTPStatusError("error", request=None, response=None)


class _FakeClient:
    """注入用フェイク httpx クライアント。実通信せず URL を記録する。"""

    ROBOTS = "User-agent: *\nDisallow: /private\n"
    PAGE = "<html><body><div class='listing' data-listing-id='X'></div></body></html>"

    def __init__(self) -> None:
        self.requested: list[str] = []

    def get(self, url: str) -> _FakeResponse:
        self.requested.append(url)
        if url.endswith("/robots.txt"):
            return _FakeResponse(200, self.ROBOTS)
        return _FakeResponse(200, self.PAGE)


class _NoParseScraper(BaseScraper):
    def parse(self, html, *, source_path):  # noqa: D401 - テスト用
        return []


def _compliance_scraper(client: _FakeClient) -> _NoParseScraper:
    return _NoParseScraper(
        _source(),
        user_agent="JapanInflationNowcastBot/test",
        contact="ops@example.com",
        client=client,
        sleeper=lambda _s: None,
    )


def test_robots_disallowed_path_not_fetched() -> None:
    client = _FakeClient()
    scraper = _compliance_scraper(client)

    with pytest.raises(DisallowedPathError):
        scraper.fetch("/private")

    # robots.txt は取得するが、不許可ページ自体は GET しない。
    assert any(u.endswith("/robots.txt") for u in client.requested)
    assert not any(u.endswith("/private") for u in client.requested)


def test_robots_allowed_path_is_fetched() -> None:
    client = _FakeClient()
    scraper = _compliance_scraper(client)

    html = scraper.fetch("/public")
    assert "data-listing-id='X'" in html
    assert any(u.endswith("/public") for u in client.requested)


def test_run_skips_disallowed_and_continues() -> None:
    client = _FakeClient()
    scraper = _NoParseScraper(
        _source(start_paths=["/private", "/public"]),
        user_agent="ua",
        contact="c",
        client=client,
        sleeper=lambda _s: None,
    )
    # /private は不許可で skip、/public は取得され、全体は落ちない。
    assert scraper.run() == []
    assert any(u.endswith("/public") for u in client.requested)
    assert not any(u.endswith("/private") for u in client.requested)
