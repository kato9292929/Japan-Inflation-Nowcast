// route ラッパ。osd の withSolanaOnlyPaywall と同じ使い勝手を JIN repo 内で再現する。
// X-PAYMENT 到達時に facilitator(PayAI) へ verify→settle を引き渡し、成功・失敗どちらでも
// X-PAYMENT-RESPONSE を返す。accepts は静的（feePayer だけ動的）で非空を保つ。

import { challenge402, corsHeaders, verifyThenSettle, type PaywallOptions } from "@/lib/x402";

type Handler = (req: Request) => Promise<Response> | Response;

export function withSolanaOnlyPaywall(handler: Handler, opts: PaywallOptions): Handler {
  return async (req: Request): Promise<Response> => {
    const xpayment = req.headers.get("x-payment");
    if (!xpayment) return challenge402(opts); // 未払い → 非空 402 accepts

    const { pass, responseHeader } = await verifyThenSettle(xpayment, opts);
    if (!pass) {
      // 検証/決済失敗 → 402 を返す。settle まで到達していれば結果を PAYMENT-RESPONSE で返す。
      const res = await challenge402(opts);
      if (responseHeader) res.headers.set("X-PAYMENT-RESPONSE", responseHeader);
      return res;
    }

    const res = await handler(req);
    for (const [k, v] of Object.entries(corsHeaders())) res.headers.set(k, v);
    if (responseHeader) res.headers.set("X-PAYMENT-RESPONSE", responseHeader);
    return res;
  };
}

export function corsPreflight(): Response {
  return new Response(null, { status: 204, headers: corsHeaders() });
}
