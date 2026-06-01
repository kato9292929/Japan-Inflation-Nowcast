"""Phase 6 受け入れ条件のテスト（API + x402, §0, §7）。

実通信なし。一時 SQLite に合成 index_values を seed し、FastAPI TestClient で叩く。
x402 検証は api.x402.verify_payment を monkeypatch して再現する。
"""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from storage.models import IndexValue

NOWCAST = "JP-INFL-NOWCAST"
BASE_DATE = date(2025, 1, 1)
LAST_DATE = date(2025, 6, 1)
GATED = ["components", "wards", "bulk"]


@pytest.fixture
def client(tmp_path, monkeypatch):
    """一時 SQLite を用意し index_values を seed して TestClient を返す。"""
    db_path = tmp_path / "jin.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    import storage.db as db

    db.get_settings.cache_clear()
    db.get_engine.cache_clear()
    db.init_db()

    with db.get_session() as s:
        for i in range(120):  # 120 日分の NOWCAST
            d = LAST_DATE - timedelta(days=i)
            s.add(
                IndexValue(
                    index_code=NOWCAST,
                    date=d,
                    value=100.0 + i * 0.01,
                    base_value=100.0,
                    base_date=BASE_DATE,
                    series_type="composite_partial",
                    coverage_pct=47.13,
                    promo_mode="excl_promo",
                    components=[
                        {"code": "JP-INFL-FOOD", "weight": 0.557, "value": 103.0},
                        {"code": "JP-INFL-HOUSING", "weight": 0.443, "value": 101.0},
                    ],
                    methodology_version="v1",
                )
            )
        for code in ("JP-INFL-FOOD", "JP-INFL-HOUSING"):
            s.add(
                IndexValue(
                    index_code=code, date=LAST_DATE, value=102.0, base_value=100.0,
                    base_date=BASE_DATE, series_type="component", methodology_version="v1",
                )
            )
        s.commit()

    from api.app import app

    yield TestClient(app)
    db.get_settings.cache_clear()
    db.get_engine.cache_clear()


def _pay_true(monkeypatch):
    monkeypatch.setattr("api.x402.verify_payment", lambda *a, **k: True)


# --------------------------------------------------------------------------- #
# 無償ルート
# --------------------------------------------------------------------------- #
def test_free_routes_ok(client) -> None:
    assert client.get("/v1/indices").status_code == 200
    assert client.get("/v1/methodology").status_code == 200

    r = client.get(f"/v1/indices/{NOWCAST}/latest")
    assert r.status_code == 200
    body = r.json()
    assert body["coverage_pct"] is not None and body["coverage_pct"] < 100.0
    assert "disclaimer" in body and body["disclaimer"]

    r90 = client.get(f"/v1/indices/{NOWCAST}/history", params={"days": 90})
    assert r90.status_code == 200
    assert len(r90.json()) <= 91


# --------------------------------------------------------------------------- #
# ゲート未払い -> 402 + payment requirements
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("resource", GATED)
def test_gated_routes_require_payment(client, resource) -> None:
    r = client.get(f"/v1/indices/{NOWCAST}/{resource}")
    assert r.status_code == 402
    req = r.json()["detail"]["payment_requirements"]
    for key in ("amount", "asset", "chain", "recipient", "facilitator_url", "resource"):
        assert key in req
    assert req["asset"] == "usdc"
    assert req["chain"] == "base"


def test_history_over_90_days_gated(client) -> None:
    r = client.get(f"/v1/indices/{NOWCAST}/history", params={"days": 400})
    assert r.status_code == 402
    assert "payment_requirements" in r.json()["detail"]


# --------------------------------------------------------------------------- #
# 検証後 -> 200 でデータを返す
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("resource", GATED)
def test_gated_routes_pass_after_payment(client, resource, monkeypatch) -> None:
    _pay_true(monkeypatch)
    r = client.get(
        f"/v1/indices/{NOWCAST}/{resource}", headers={"X-PAYMENT": "proof"}
    )
    assert r.status_code == 200
    assert r.json()["index_code"] == NOWCAST


def test_history_over_90_days_after_payment(client, monkeypatch) -> None:
    _pay_true(monkeypatch)
    r = client.get(
        f"/v1/indices/{NOWCAST}/history",
        params={"days": 400},
        headers={"X-PAYMENT": "proof"},
    )
    assert r.status_code == 200
    assert len(r.json()) == 120  # 全 120 日


# --------------------------------------------------------------------------- #
# 表記: 公式CPI 誤認なし（§0）
# --------------------------------------------------------------------------- #
def test_no_official_cpi_misrepresentation(client, monkeypatch) -> None:
    _pay_true(monkeypatch)
    blobs = []
    for path in (
        "/v1/indices",
        f"/v1/indices/{NOWCAST}/latest",
        "/v1/methodology",
        f"/v1/indices/{NOWCAST}/components",
        f"/v1/indices/{NOWCAST}/bulk",
    ):
        resp = client.get(path, headers={"X-PAYMENT": "proof"})
        blobs.append(json.dumps(resp.json(), ensure_ascii=False))
    text = "\n".join(blobs)

    # 「公式 CPI」「CPI そのもの」と誤認させる表記は一切無い（§0）。
    for bad in ("公式 CPI", "公式CPI", "CPI そのもの", "CPIそのもの"):
        assert bad not in text
    # 英語 "official" は否定形（NOT official）でのみ現れる（誤認の主張をしない）。
    assert text.count("official") == text.count("NOT official")
