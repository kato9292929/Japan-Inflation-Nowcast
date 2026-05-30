"""x402 課金ゲート（§7）。

方針:
- 既存ミドルウェア/facilitator を再利用する前提のフックを用意する。
- 無ければ 402 応答に payment requirements（USDC, Base, amount, recipient, facilitator URL）
  を返し、X-PAYMENT ヘッダを検証してから本体を返す標準フローを実装する。
- 価格は config 化（route -> price）。

Phase 0 はシグネチャと値オブジェクトのみ。検証本体は Phase 6 で実装する。
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request


@dataclass(frozen=True)
class PaymentRequirements:
    """402 応答に載せる支払い要件（§7）。"""

    amount: str
    asset: str
    chain: str
    recipient: str
    facilitator_url: str
    resource: str


# ルート -> 価格（USDC, 文字列で精度保持）。Phase 6 で config 化する。
ROUTE_PRICES: dict[str, str] = {
    "components": "0.01",
    "categories": "0.01",
    "wards": "0.01",
    "history_extended": "0.05",
    "bulk": "0.50",
}


def build_requirements(resource: str, amount: str) -> PaymentRequirements:
    """支払い要件オブジェクトを設定から組み立てる（§7, §10）。"""
    raise NotImplementedError("Phase 6: 設定から payment requirements を組み立てる")


def verify_payment(request: Request, requirements: PaymentRequirements) -> bool:
    """X-PAYMENT ヘッダを facilitator で検証する（§7）。検証できれば True。"""
    raise NotImplementedError("Phase 6: X-PAYMENT の facilitator 検証を実装する")


async def require_payment(request: Request, resource: str) -> None:
    """課金ルートの FastAPI 依存。未払いなら 402 を payment requirements 付きで送出する。"""
    raise NotImplementedError("Phase 6: 402 ゲートフローを実装する")
