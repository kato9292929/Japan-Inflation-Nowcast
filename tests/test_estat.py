"""e-Stat フェッチャーのテスト（実通信なし・API レスポンスをモック, §8）。

このサンドボックスからは api.e-stat.go.jp に出られないため、HTTP クライアントを注入して
モック応答を返す。live は運用者の環境で appId を入れて実行する前提。
"""

from __future__ import annotations

import shutil
from pathlib import Path

import httpx
import pytest
import yaml

from scrapers.base import SourceConfig
from scrapers.estat.client import EStatClient, EStatError
from scrapers.estat.food import EStatFoodFetcher, parse_price_records
from scrapers.estat.weights import (
    fetch_food_weights,
    parse_food_weights,
    update_food_weights,
    validate_weights,
)

BASKETS = Path(__file__).resolve().parent.parent / "config" / "baskets.yaml"

# --- モック JSON（getStatsData 価格応答）------------------------------------ #
PRICE_JSON = {
    "GET_STATS_DATA": {
        "RESULT": {"STATUS": 0, "ERROR_MSG": "正常に終了しました。"},
        "STATISTICAL_DATA": {
            "CLASS_INF": {
                "CLASS_OBJ": [
                    {
                        "@id": "cat01",
                        "CLASS": [
                            {"@code": "001", "@name": "うるち米"},
                            {"@code": "002", "@name": "食パン"},
                        ],
                    },
                    {"@id": "area", "CLASS": {"@code": "13100", "@name": "東京都区部"}},
                ]
            },
            "DATA_INF": {
                "VALUE": [
                    {"@cat01": "001", "@area": "13100", "@time": "2025000606",
                     "@unit": "円", "$": "500"},
                    {"@cat01": "002", "@area": "13100", "@time": "2025000606",
                     "@unit": "円", "$": "420"},
                    # 欠測（"-"）は捨てる。
                    {"@cat01": "002", "@area": "13100", "@time": "2025000505",
                     "@unit": "円", "$": "-"},
                ]
            },
        },
    }
}

# --- モック JSON（CPI 食料ウェイト応答）------------------------------------- #
WEIGHTS_JSON = {
    "GET_STATS_DATA": {
        "RESULT": {"STATUS": 0, "ERROR_MSG": "正常"},
        "STATISTICAL_DATA": {
            "CLASS_INF": {
                "CLASS_OBJ": {
                    "@id": "cat01",
                    "CLASS": [
                        {"@code": "01", "@name": "穀類"},
                        {"@code": "02", "@name": "魚介類"},
                        {"@code": "03", "@name": "肉類"},
                    ],
                }
            },
            "DATA_INF": {
                "VALUE": [
                    {"@cat01": "01", "$": "232"},
                    {"@cat01": "02", "$": "188"},
                    {"@cat01": "03", "$": "274"},
                ]
            },
        },
    }
}


class _FakeResp:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("err", request=None, response=None)

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, payload):
        self._payload = payload
        self.calls = []

    def get(self, url, params=None):
        self.calls.append((url, params))
        return _FakeResp(self._payload)


class _RaisingClient:
    def get(self, url, params=None):
        raise httpx.ConnectError("no network")


# --------------------------------------------------------------------------- #
# 1) 価格レコードが正しい raw スキーマで生成される
# --------------------------------------------------------------------------- #
def test_food_fetcher_builds_raw_records() -> None:
    cfg = SourceConfig(
        id="estat_food", enabled=True, type="estat",
        options={
            "stats_data_id": "0003TEST",
            "item_class_id": "cat01",
            "default_unit": "g",
            "unit_size": 100,
            "category_map": {"001": "穀類", "食パン": "穀類"},
        },
    )
    fetcher = EStatFoodFetcher(cfg, client=_FakeClient(PRICE_JSON), app_id="DUMMY")
    records = fetcher.run()

    assert len(records) == 2  # 欠測 1 行は除外
    by_id = {r["item_id"]: r for r in records}

    r1 = by_id["001"]
    assert r1["source"] == "estat_food"
    assert r1["product_name"] == "うるち米"
    assert r1["category"] == "穀類"          # code でマップ
    assert r1["price"] == 500.0 and isinstance(r1["price"], float)
    assert r1["unit"] == "g" and r1["unit_size"] == 100.0
    assert r1["is_promo"] is False
    assert r1["raw_payload"]["@cat01"] == "001"

    assert by_id["002"]["category"] == "穀類"  # 品目名でマップ


def test_parse_price_records_passthrough_unit_when_no_default() -> None:
    records = parse_price_records(PRICE_JSON, source="x", options={})
    # default_unit 未指定なら API の @unit を使う。
    assert records[0]["unit"] == "円"
    # category_map 無しなら品目名をそのまま category に。
    assert records[0]["category"] == "うるち米"


# --------------------------------------------------------------------------- #
# 2) ウェイト取得ヘルパーが food.categories.weight を更新する
# --------------------------------------------------------------------------- #
def test_parse_and_validate_weights() -> None:
    weights = parse_food_weights(WEIGHTS_JSON)
    assert weights == {"穀類": 232.0, "魚介類": 188.0, "肉類": 274.0}
    validate_weights(weights)  # 例外が出ない


def test_fetch_food_weights_with_injected_client() -> None:
    weights = fetch_food_weights("0003W", app_id="DUMMY", client=_FakeClient(WEIGHTS_JSON))
    assert weights["穀類"] == 232.0


def test_update_food_weights_rewrites_baskets(tmp_path) -> None:
    baskets = tmp_path / "baskets.yaml"
    shutil.copy(BASKETS, baskets)

    weights = parse_food_weights(WEIGHTS_JSON)
    n = update_food_weights(weights, baskets_path=baskets)
    assert n == 3

    data = yaml.safe_load(baskets.read_text(encoding="utf-8"))
    cat_w = {c["name"]: c["weight"] for c in data["food"]["categories"]}
    assert cat_w["穀類"] == 232
    assert cat_w["魚介類"] == 188
    assert cat_w["肉類"] == 274
    # 桁・合計の健全性。
    assert sum(weights.values()) > 0


def test_validate_weights_rejects_bad() -> None:
    with pytest.raises(ValueError):
        validate_weights({})
    with pytest.raises(ValueError):
        validate_weights({"穀類": 0.0})


# --------------------------------------------------------------------------- #
# 3) appId 未設定・通信失敗は安全に空/例外ハンドリング（全体を落とさない）
# --------------------------------------------------------------------------- #
def test_missing_app_id_returns_empty() -> None:
    cfg = SourceConfig(id="e", enabled=True, type="estat", options={"stats_data_id": "X"})
    fetcher = EStatFoodFetcher(cfg, client=_FakeClient(PRICE_JSON), app_id="")
    assert fetcher.run() == []


def test_missing_stats_data_id_returns_empty() -> None:
    cfg = SourceConfig(id="e", enabled=True, type="estat", options={})
    fetcher = EStatFoodFetcher(cfg, client=_FakeClient(PRICE_JSON), app_id="DUMMY")
    assert fetcher.run() == []


def test_network_failure_returns_empty() -> None:
    cfg = SourceConfig(id="e", enabled=True, type="estat", options={"stats_data_id": "X"})
    fetcher = EStatFoodFetcher(cfg, client=_RaisingClient(), app_id="DUMMY")
    assert fetcher.run() == []  # 例外を握って空を返す


def test_client_raises_on_empty_app_id_directly() -> None:
    client = EStatClient("", client=_FakeClient(PRICE_JSON))
    with pytest.raises(EStatError):
        client.get_stats_data("X")


def test_client_raises_on_api_status_error() -> None:
    bad = {"GET_STATS_DATA": {"RESULT": {"STATUS": 1, "ERROR_MSG": "エラー"}}}
    client = EStatClient("DUMMY", client=_FakeClient(bad))
    with pytest.raises(EStatError):
        client.get_stats_data("X")
