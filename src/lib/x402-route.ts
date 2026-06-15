// route ラッパ。osd の withSolanaOnlyPaywall と同じ使い勝手を JIN repo 内で再現する。

import { challenge402, corsHeaders, verifyPayment, type PaywallOptions } from "@/lib/x402";

type Handler = (req: Request) => Promise<Response> | Response;

export function withSolanaOnlyPaywall(handler: Handler, opts: PaywallOptions): Handler {
  return async (req: Request): Promise<Response> => {
    const paid = await verifyPayment(req, opts);
    if (!paid) return challenge402(opts);
    const res = await handler(req);
    for (const [k, v] of Object.entries(corsHeaders())) res.headers.set(k, v);
    return res;
  };
}

export function corsPreflight(): Response {
  return new Response(null, { status: 204, headers: corsHeaders() });
}
