"""オンチェーンオラクル publisher（任意・§1, §9 Phase 8）。

日次の合成値（JP-INFL-NOWCAST）を on-chain に publish する。Pyth / Chainlink 互換の
数値エンコード（int price + expo）で index_code・date・value・coverage_pct・
methodology_version を載せる。

非交渉（テスト方針）:
- 実 publish はテストしない。web3 クライアントは注入可能にし、payload 構築・エンコードの
  単体テストのみ（実送信なし）。
- 鍵/RPC/コントラクトが揃わなければ publish をスキップして落ちない（既定は無効）。

web3 はオプション依存（pyproject extra: oracle）。本モジュールは web3 を**トップレベルで
import しない**（未インストールでも payload/encode は動く）。実送信は運用者環境で。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, Protocol

# 価格スケール（Pyth 互換: 整数 price と expo）。
VALUE_EXPO = -8
VALUE_SCALE = 10 ** (-VALUE_EXPO)


@dataclass(frozen=True)
class OracleConfig:
    """publish 先の設定（env 由来）。3 つ揃って初めて enabled。"""

    rpc_url: str = ""
    private_key: str = ""
    contract: str = ""
    chain: str = "base-sepolia"

    @property
    def enabled(self) -> bool:
        return bool(self.rpc_url and self.private_key and self.contract)


def config_from_settings() -> OracleConfig:
    from storage.db import get_settings

    s = get_settings()
    return OracleConfig(
        rpc_url=s.oracle_rpc_url,
        private_key=s.oracle_private_key,
        contract=s.oracle_contract,
        chain=s.oracle_chain,
    )


class OracleClient(Protocol):
    """注入可能な publish クライアントの最小インターフェース（web3 実装は運用者側）。"""

    def publish(self, encoded: dict[str, Any]) -> str:  # 返り値: tx hash
        ...


def build_payload(value: dict[str, Any]) -> dict[str, Any]:
    """IndexValue 相当 dict から publish ペイロード（人間可読）を作る。"""
    d = value.get("date")
    date_iso = d.isoformat() if isinstance(d, date) else str(d)
    return {
        "index_code": value.get("index_code"),
        "date": date_iso,
        "value": float(value["value"]),
        "coverage_pct": value.get("coverage_pct"),
        "methodology_version": value.get("methodology_version"),
    }


def encode_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """ペイロードを Pyth/Chainlink 互換の数値エンコードに変換する（実送信用）。

    - value -> 整数 price（expo=-8）。
    - coverage_pct -> bps（×100 の整数, None は -1）。
    - date(YYYY-MM-DD) -> 整数 YYYYMMDD。
    """
    value = float(payload["value"])
    cov = payload.get("coverage_pct")
    date_int = int(str(payload["date"]).replace("-", "")) if payload.get("date") else 0
    return {
        "index_code": str(payload.get("index_code") or ""),
        "date_int": date_int,
        "price": int(round(value * VALUE_SCALE)),
        "expo": VALUE_EXPO,
        "coverage_bps": int(round(cov * 100)) if cov is not None else -1,
        "methodology_version": str(payload.get("methodology_version") or ""),
        "publish_time": int(datetime.now(UTC).timestamp()),
    }


def publish(
    value: dict[str, Any],
    *,
    client: OracleClient | None = None,
    config: OracleConfig | None = None,
) -> dict[str, Any]:
    """合成値を publish する。鍵等が無ければスキップ（落ちない）。

    Returns: {"status": "published"|"skipped", ...}。
    """
    cfg = config if config is not None else config_from_settings()
    payload = build_payload(value)
    encoded = encode_payload(payload)

    if not cfg.enabled:
        return {"status": "skipped", "reason": "oracle disabled (env 未設定)", "encoded": encoded}
    if client is None:
        # live は運用者環境で Web3OracleClient を注入する（実送信はテストしない）。
        return {"status": "skipped", "reason": "no client injected", "encoded": encoded}

    tx = client.publish(encoded)
    return {"status": "published", "tx": tx, "encoded": encoded, "chain": cfg.chain}


def publish_latest(
    session: Any,
    *,
    client: OracleClient | None = None,
    config: OracleConfig | None = None,
    index_code: str = "JP-INFL-NOWCAST",
) -> dict[str, Any]:
    """index_values の最新 NOWCAST を読み、publish する（daily の任意ステップ）。"""
    from sqlmodel import select

    from storage.models import IndexValue

    row = session.exec(
        select(IndexValue)
        .where(IndexValue.index_code == index_code)
        .order_by(IndexValue.date.desc())
    ).first()
    if row is None:
        return {"status": "skipped", "reason": "no index value"}

    value = {
        "index_code": row.index_code,
        "date": row.date,
        "value": row.value,
        "coverage_pct": row.coverage_pct,
        "methodology_version": row.methodology_version,
    }
    return publish(value, client=client, config=config)
