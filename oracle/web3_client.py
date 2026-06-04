"""web3 ベースの Oracle クライアント参照実装（運用者環境用・テスト対象外）。

web3 はオプション依存（pyproject extra: oracle）。本ファイルは web3 を**遅延 import**し、
未インストールでも他モジュールの import を壊さない。実送信は運用者の環境（testnet 先行）で
行い、本リポジトリのテストには含めない（§9 Phase 8）。

publisher.publish(value, client=Web3OracleClient(...)) のように注入して使う。
"""

from __future__ import annotations

from typing import Any

from oracle.publisher import OracleConfig


class Web3OracleClient:
    """encoded ペイロードをコントラクトに送る web3 実装（運用者が ABI を pin）。"""

    def __init__(self, config: OracleConfig, *, abi: list[dict[str, Any]] | None = None) -> None:
        self.config = config
        self.abi = abi or []

    def publish(self, encoded: dict[str, Any]) -> str:
        """encoded を on-chain に送り tx hash を返す（運用者環境でのみ実行）。"""
        # 遅延 import: web3 が無い環境では他のコードを壊さない。
        try:
            from web3 import Web3  # noqa: F401
        except ModuleNotFoundError as exc:  # pragma: no cover - 運用者環境のみ
            raise RuntimeError(
                "web3 が未インストールです。`uv sync --extra oracle` を実行してください"
            ) from exc

        # 実装（運用者が pin する ABI / 関数名に合わせて送信）:
        #   w3 = Web3(Web3.HTTPProvider(self.config.rpc_url))
        #   acct = w3.eth.account.from_key(self.config.private_key)
        #   contract = w3.eth.contract(address=self.config.contract, abi=self.abi)
        #   tx = contract.functions.submit(...encoded...).build_transaction(...)
        #   signed = acct.sign_transaction(tx)
        #   h = w3.eth.send_raw_transaction(signed.rawTransaction)
        #   return h.hex()
        raise NotImplementedError(  # pragma: no cover - 運用者が ABI に合わせて実装
            "Web3OracleClient.publish は運用者環境で ABI/関数に合わせて実装する"
        )
