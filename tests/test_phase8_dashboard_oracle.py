"""Phase 8 のテスト（ダッシュボード描画 + オラクル payload, §0, §1）。

実通信・実 publish はしない（web3 クライアントは注入、API は TestClient）。
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from dashboard.render import build_headline_view, coverage_label, render_html
from oracle.publisher import (
    OracleConfig,
    build_payload,
    encode_payload,
    publish,
    publish_latest,
)
from storage.models import IndexValue

NOWCAST = "JP-INFL-NOWCAST"
BASE_DATE = date(2025, 1, 1)
LAST_DATE = date(2025, 6, 1)


# --------------------------------------------------------------------------- #
# ダッシュボード描画（純粋関数）
# --------------------------------------------------------------------------- #
def _latest(coverage=47.13):
    return {
        "index_code": NOWCAST, "date": "2025-06-01", "value": 103.234,
        "coverage_pct": coverage, "yoy_pct": 2.5, "series_type": "composite_partial",
        "methodology_version": "v1",
        "disclaimer": "This is an independent nowcast (速報), NOT official CPI.",
    }


def _history(n=90):
    return [
        {"index_code": NOWCAST, "date": f"2025-03-{(i % 28) + 1:02d}", "value": 100.0 + i * 0.05}
        for i in range(n)
    ]


def test_build_headline_view_formats_headline_and_coverage() -> None:
    view = build_headline_view(_latest(), _history(90))
    assert view["index_code"] == NOWCAST
    assert view["value"] == pytest.approx(103.23)  # 2 桁丸め
    assert view["coverage_pct"] < 100.0
    assert view["is_partial"] is True
    assert "カバー" in view["coverage_label"]
    assert view["n_points"] == 90
    assert view["disclaimer"]


def test_coverage_label_below_100() -> None:
    assert "47.1" in coverage_label(47.13)
    assert "100% 未満" in coverage_label(47.13)
    assert coverage_label(None) == "カバー率: 不明"


def test_render_html_shows_disclaimer_coverage_and_no_official_misrep() -> None:
    html_text = render_html(build_headline_view(_latest(), _history(30)))
    assert "<html" in html_text
    assert "ナウキャスト" in html_text          # 速報であることを明示
    assert "カバー" in html_text                # coverage 明示
    assert "NOT official CPI" in html_text       # 否定形の免責
    # §0: 「公式 CPI」「CPI そのもの」と誤認させる表記が無い。
    for bad in ("公式 CPI", "公式CPI", "CPI そのもの", "CPIそのもの"):
        assert bad not in html_text


# --------------------------------------------------------------------------- #
# ダッシュボード API（/dashboard, 無償・HTML）
# --------------------------------------------------------------------------- #
@pytest.fixture
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "jin.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    import storage.db as db

    db.get_settings.cache_clear()
    db.get_engine.cache_clear()
    db.init_db()
    with db.get_session() as s:
        for i in range(120):
            s.add(IndexValue(
                index_code=NOWCAST, date=LAST_DATE - timedelta(days=i),
                value=100.0 + i * 0.01, base_value=100.0, base_date=BASE_DATE,
                series_type="composite_partial", coverage_pct=47.13,
                promo_mode="excl_promo", methodology_version="v1",
            ))
        s.commit()
    from api.app import app

    yield TestClient(app)
    db.get_settings.cache_clear()
    db.get_engine.cache_clear()


def test_dashboard_route_returns_html(client) -> None:
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    body = r.text
    assert "カバー" in body and "47.1" in body
    assert "NOT official CPI" in body
    for bad in ("公式 CPI", "CPI そのもの"):
        assert bad not in body


# --------------------------------------------------------------------------- #
# オラクル payload / encode（実送信なし）
# --------------------------------------------------------------------------- #
def _value():
    return {
        "index_code": NOWCAST, "date": date(2025, 6, 1), "value": 103.2,
        "coverage_pct": 47.13, "methodology_version": "v1",
    }


def test_build_and_encode_payload() -> None:
    payload = build_payload(_value())
    assert payload["index_code"] == NOWCAST
    assert payload["date"] == "2025-06-01"
    assert payload["value"] == 103.2

    enc = encode_payload(payload)
    assert enc["price"] == round(103.2 * 10**8)
    assert enc["expo"] == -8
    assert enc["date_int"] == 20250601
    assert enc["coverage_bps"] == 4713  # 47.13% -> bps
    assert enc["methodology_version"] == "v1"
    assert enc["index_code"] == NOWCAST


def test_publish_skips_when_disabled() -> None:
    res = publish(_value(), config=OracleConfig())  # env 未設定相当 -> 無効
    assert res["status"] == "skipped"
    assert "encoded" in res  # encode 自体は出来る


class _FakeOracleClient:
    def __init__(self):
        self.sent = None

    def publish(self, encoded):
        self.sent = encoded
        return "0xTX_FAKE"


def test_publish_sends_via_injected_client() -> None:
    cfg = OracleConfig(rpc_url="http://rpc", private_key="0xkey", contract="0xabc")
    assert cfg.enabled is True
    fake = _FakeOracleClient()
    res = publish(_value(), client=fake, config=cfg)
    assert res["status"] == "published"
    assert res["tx"] == "0xTX_FAKE"
    assert fake.sent["price"] == round(103.2 * 10**8)


def test_publish_latest_skips_without_env(client) -> None:
    # client フィクスチャの DB を使う（NOWCAST seed 済み）。env 未設定 -> skipped。
    import storage.db as db

    with db.get_session() as s:
        res = publish_latest(s)
    assert res["status"] == "skipped"
