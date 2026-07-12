// route ラッパ（OSD PR #16 と同型）。未払いも支払い済みも withX402 に委譲する。
// self-build（手組み accepts / 手組み feePayer / 手組み verify・settle）は撤去。
// withX402 が top-level x402Version:2 + PAYMENT-REQUIRED ヘッダ + v2 CAIP-2 leg（amount）
// + live feePayer を出す。
import type { PaymentOption } from "@x402/core/http";
import type { RouteConfig } from "@x402/core/server";
import type { Network } from "@x402/core/types";
import { withX402 } from "@x402/next";
import { NextResponse, type NextRequest } from "next/server";
import { x402Server } from "./x402-server";

const SOLANA_NETWORK: Network = "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp"; // CAIP-2
const PAY_TO = process.env.X402_RECIPIENT ?? "4s8XQC2WzRfgH8Xiep7ybnCW11VKRCMwxQF6jknx3VPf";
// resource は絶対URL。本番ドメインを既定に（PUBLIC_BASE_URL で上書き可）。
const PUBLIC_BASE_URL = process.env.PUBLIC_BASE_URL ?? "https://jin-orcin-pi.vercel.app";

export type PaywallOptions = { price: string; description: string; resourcePath: string };

// price は Money 文字列（"$0.02"）。amount/feePayer は書かない＝SDK が getSupported から入れる。
function buildSolanaOnlyRouteConfig(
  price: string,
  description: string,
  resourcePath: string,
): RouteConfig {
  const resource = `${PUBLIC_BASE_URL}${resourcePath}`;
  const accepts: PaymentOption[] = [
    {
      scheme: "exact",
      network: SOLANA_NETWORK,
      payTo: PAY_TO,
      price,
      extra: { resource },
    },
  ];
  return { accepts, description, resource };
}

// CORS。PAYMENT-REQUIRED / PAYMENT-RESPONSE を expose（クライアントがヘッダを読めるように）。
export function corsHeaders(): Record<string, string> {
  return {
    "access-control-allow-origin": "*",
    "access-control-allow-methods": "GET, OPTIONS",
    "access-control-allow-headers": "Content-Type, X-PAYMENT",
    "access-control-expose-headers": "PAYMENT-REQUIRED, PAYMENT-RESPONSE, X-PAYMENT-RESPONSE",
  };
}

export function corsPreflight(): NextResponse {
  return new NextResponse(null, { status: 204, headers: corsHeaders() });
}

function applyCors(res: NextResponse): NextResponse {
  for (const [k, v] of Object.entries(corsHeaders())) res.headers.set(k, v);
  return res;
}

export function withSolanaOnlyPaywall(
  handler: (req: NextRequest) => Promise<NextResponse> | NextResponse,
  opts: PaywallOptions,
) {
  const wrapped = withX402(
    async (req: NextRequest) => handler(req),
    buildSolanaOnlyRouteConfig(opts.price, opts.description, opts.resourcePath),
    x402Server,
    undefined, // paywallConfig
    undefined, // paywall
    true, // syncFacilitatorOnStart（false だと facilitator 未init → 500/空）
  );
  return async (req: NextRequest): Promise<NextResponse> => {
    if (req.method === "OPTIONS") return corsPreflight();
    // 未払い→402(v2ヘッダ)・支払い済→verify/settle、両方 withX402 が担当。
    return applyCors(await wrapped(req));
  };
}
