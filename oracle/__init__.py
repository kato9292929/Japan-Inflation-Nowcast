"""オンチェーンオラクル publish（任意, §1, §9 Phase 8）。

最新の合成値（JP-INFL-NOWCAST）を Pyth / Chainlink 互換で publish する。既定は無効
（env が揃ったときだけ実行）。実送信は運用者環境（testnet 先行）で、テストには含めない。
"""

from oracle.publisher import (
    OracleConfig,
    build_payload,
    encode_payload,
    publish,
    publish_latest,
)

__all__ = [
    "OracleConfig",
    "build_payload",
    "encode_payload",
    "publish",
    "publish_latest",
]
