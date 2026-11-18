// x402 discovery（情報用）。実際の支払いチャレンジ（402 v2 / PAYMENT-REQUIRED ヘッダ）は
// 各 endpoint 自身が native withX402 で返す。ここは endpoint とネットワーク/価格の列挙のみで、
// 402 の wire 形は self-build しない（native に一本化）。
import { corsHeaders } from "@/lib/x402-route";
import { PAY_TO, PUBLIC_BASE_URL, SOLANA_NETWORK, USDC_ASSET } from "@/lib/x402-config";
import { COUNTRIES } from "@/lib/inflation-data";
import { inflationPaymentsEnabled, INFLATION_PRICE } from "@/lib/inflation-payment";
import { LNBTC_PRICES_MSAT, lnbtcConfig } from "@/lib/lnbtc-config";
import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

export const GET = async (req: Request) => {
  const origin = new URL(req.url).origin;
  const inflationPaid = inflationPaymentsEnabled();
  const lnbtc = lnbtcConfig();
  return NextResponse.json(
    {
      source: "japan-inflation-nowcast",
      note: "公的CPIとJIN店頭観測。店頭観測は非公的指数。予測は含まない。",
      x402: "native withX402 (v2). Payment challenge is served on each endpoint (402 with PAYMENT-REQUIRED header).",
      network: SOLANA_NETWORK,
      asset: USDC_ASSET,
      payTo: PAY_TO,
      // Bitcoin Lightning（x402 exact/lnbtc）。有効なときだけ。invoice は各 endpoint の 402 に載る。
      lnbtc: lnbtc
        ? {
            network: lnbtc.network,
            asset: "BTC",
            payTo: lnbtc.payTo,
            prices_msat: Object.fromEntries(
              Object.entries(LNBTC_PRICES_MSAT).map(([path, msat]) => [`${origin}${path}`, msat]),
            ),
          }
        : null,
      endpoints: [
        { resource: `${origin}/api/jin/series`, price: "$0.01", free: false },
        { resource: `${origin}/api/jin/movers`, price: "$0.02", free: false },
        { resource: `${origin}/api/jin/latest`, price: null, free: true },
        { resource: `${PUBLIC_BASE_URL}/api/inflation/latest`, price: null, free: true },
        ...COUNTRIES.map((country) => ({
          resource: `${PUBLIC_BASE_URL}/api/inflation/${country}`,
          price: inflationPaid ? INFLATION_PRICE : null,
          configured_price: INFLATION_PRICE,
          free: !inflationPaid,
        })),
      ],
    },
    { headers: corsHeaders() },
  );
};
