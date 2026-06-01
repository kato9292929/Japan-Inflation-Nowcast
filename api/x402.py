"""x402 課金ゲート（§7）。

方針:
- 既存ミドルウェア/facilitator を再利用する前提のフックを用意する。
- 無ければ 402 応答に payment requirements（USDC, Base, amount, recipient, facilitator URL）
  を返し、X-PAYMENT ヘッダを検証してから本体を返す標準フローを実装する。
- 価格は config 化（route -> price）。

テスト容易性: facilitator への HTTP クライアントは注入可能。実通信せず検証できる。
facilitator URL 未設定なら検証不能としてゲートは閉じる（False）。テストは
verify_payment の差し替え（monkeypatch）またはクライアント注入で 200 を再現できる。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import httpx
from fastapi import HTTPException, Request

from storage.db import get_settings


@dataclass(frozen=True)
class PaymentRequirements:
    """402 応答に載せる支払い要件（§7）。"""

    amount: str
    asset: str
    chain: str
    recipient: str
    facilitator_url: str
    resource: str


# ルート -> 価格（USDC, 文字列で精度保持）。config 化済み（§7）。
ROUTE_PRICES: dict[str, str] = {
    "components": "0.01",
    "categories": "0.01",
    "wards": "0.01",
    "history_extended": "0.05",
    "bulk": "0.50",
}


def build_requirements(resource: str, amount: str) -> PaymentRequirements:
    """支払い要件オブジェクトを設定（.env）から組み立てる（§7, §10）。"""
    s = get_settings()
    return PaymentRequirements(
        amount=amount,
        asset=s.x402_asset,
        chain=s.x402_chain,
        recipient=s.x402_recipient_address,
        facilitator_url=s.x402_facilitator_url,
        resource=resource,
    )


def verify_payment(
    request: Request,
    requirements: PaymentRequirements,
    *,
    client: httpx.Client | None = None,
) -> bool:
    """X-PAYMENT ヘッダを facilitator で検証する（§7）。検証できれば True。

    - X-PAYMENT が無い -> False。
    - facilitator URL 未設定 -> 検証不能としてゲートを閉じる（False）。
    - facilitator が valid を返せば True。通信/解析失敗は False（安全側）。
    """
    payment = request.headers.get("X-PAYMENT")
    if not payment:
        return False
    if not requirements.facilitator_url:
        return False

    owns = client is None
    c = client or httpx.Client(timeout=10.0)
    try:
        resp = c.post(
            f"{requirements.facilitator_url.rstrip('/')}/verify",
            json={"payment": payment, "requirements": asdict(requirements)},
        )
        if resp.status_code != 200:
            return False
        data = resp.json()
        return bool(data.get("valid", data.get("isValid", False)))
    except Exception:  # noqa: BLE001  検証不能は安全側で False
        return False
    finally:
        if owns:
            c.close()


async def require_payment(request: Request, resource: str) -> None:
    """課金ルートのゲート本体。未払いなら 402 を payment requirements 付きで送出する。"""
    amount = ROUTE_PRICES.get(resource, "0.01")
    requirements = build_requirements(resource, amount)
    if verify_payment(request, requirements):
        return
    payload = asdict(requirements)
    raise HTTPException(
        status_code=402,
        detail={"error": "payment required", "payment_requirements": payload},
        headers={
            "X-Payment-Amount": requirements.amount,
            "X-Payment-Asset": requirements.asset,
            "X-Payment-Chain": requirements.chain,
            "X-Payment-Recipient": requirements.recipient,
        },
    )


def payment_gate(resource: str):
    """FastAPI 依存ファクトリ。``Depends(payment_gate("components"))`` で使う。"""

    async def dependency(request: Request) -> None:
        await require_payment(request, resource)

    return dependency


def history_gate():
    """history 専用ゲート: days > 90 のときのみ 'history_extended' で課金する（§7）。"""

    async def dependency(request: Request) -> None:
        try:
            days = int(request.query_params.get("days", 90))
        except (TypeError, ValueError):
            days = 90
        if days > 90:
            await require_payment(request, "history_extended")

    return dependency
