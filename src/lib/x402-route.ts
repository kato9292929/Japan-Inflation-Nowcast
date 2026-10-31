// route ラッパ（OSD PR #16 と同型）。未払いも支払い済みも withX402 に委譲する。
// self-build（手組み accepts / 手組み feePayer / 手組み verify・settle）は撤去。
// withX402 が top-level x402Version:2 + PAYMENT-REQUIRED ヘッダ + v2 CAIP-2 leg（amount）
// + live feePayer を出す。
import type { PaymentOption } from "@x402/core/http";
import type { RouteConfig } from "@x402/core/server";
import { withX402 } from "@x402/next";
import { NextRequest, NextResponse } from "next/server";
import { x402Server } from "./x402-server";
import { PAY_TO, PUBLIC_BASE_URL, SOLANA_NETWORK, USDC_ASSET } from "./x402-config";
import { priceToAtomic, recordSale, settledTx } from "./sales-log";
import { withDeliveryReceipts } from "./delivery-receipt";
import { receiptSeller } from "./receipts";

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
    "access-control-allow-headers": "Content-Type, X-PAYMENT, PAYMENT-SIGNATURE, X-Payment-Refetch",
    "access-control-expose-headers": "PAYMENT-REQUIRED, PAYMENT-RESPONSE, X-PAYMENT-RESPONSE, X-Delivery-Receipt",
  };
}

export function corsPreflight(): NextResponse {
  return new NextResponse(null, { status: 204, headers: corsHeaders() });
}

function applyCors(res: NextResponse): NextResponse {
  for (const [k, v] of Object.entries(corsHeaders())) res.headers.set(k, v);
  return res;
}

const asNext = (req: Request): NextRequest => (req instanceof NextRequest ? req : new NextRequest(req));
const toNext = (res: Response): NextResponse =>
  res instanceof NextResponse ? res : new NextResponse(res.body, { status: res.status, statusText: res.statusText, headers: res.headers });

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
  // Delivery Receipt: settle 成功の 200 は本文を記録してからレシートを付けて返す。
  // X-Payment-Refetch 付きの再取得は withX402 を通さない（verify/settle を走らせない）。
  const resource = `${PUBLIC_BASE_URL}${opts.resourcePath}`;
  // 初回の要求で作る（ビルド時やテストの import で鍵を要求しない。起動時の確認は src/instrumentation.ts）。
  let withReceipts: ((req: Request) => Promise<Response>) | null = null;
  const receipts = () => (withReceipts ??= withDeliveryReceipts(receiptSeller(), {
    paywalled: (req) => wrapped(asNext(req)),
    handler: async (req) => handler(asNext(req)),
    resource,
    requirement: { network: SOLANA_NETWORK, payTo: PAY_TO, asset: USDC_ASSET, amount: priceToAtomic(opts.price) },
  }));
  return async (req: NextRequest): Promise<NextResponse> => {
    if (req.method === "OPTIONS") return corsPreflight();
    // 未払い→402(v2ヘッダ)・支払い済→verify/settle、両方 withX402 が担当。
    const res = toNext(await receipts()(req));
    // settle に成功したら売り手ログに1件記録する（支払いの処理は変えない。記録に失敗しても応答は返す）
    const tx = settledTx(res.headers.get("payment-response"));
    if (tx) {
      try {
        await recordSale({
          tx_signature: tx,
          endpoint: `${PUBLIC_BASE_URL}${opts.resourcePath}`,
          amount: priceToAtomic(opts.price),
          time_utc: new Date().toISOString(),
        });
      } catch (e) {
        console.error("[sales-log] 記録に失敗", tx, e);
      }
    }
    return applyCors(res);
  };
}
