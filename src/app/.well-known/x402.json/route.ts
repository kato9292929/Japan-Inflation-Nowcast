// x402 discovery（情報用）。実際の支払いチャレンジ（402 v2 / PAYMENT-REQUIRED ヘッダ）は
// 各 endpoint 自身が native withX402 で返す。ここは endpoint とネットワーク/価格の列挙のみで、
// 402 の wire 形は self-build しない（native に一本化）。
import { corsHeaders } from "@/lib/x402-route";
import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

const NETWORK = "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp"; // CAIP-2
const PAY_TO = process.env.X402_RECIPIENT ?? "4s8XQC2WzRfgH8Xiep7ybnCW11VKRCMwxQF6jknx3VPf";
const ASSET = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"; // Solana USDC mint

export const GET = async (req: Request) => {
  const origin = new URL(req.url).origin;
  return NextResponse.json(
    {
      source: "japan-inflation-nowcast",
      note: "observation data; not official CPI; not a forecast",
      x402: "native withX402 (v2). Payment challenge is served on each endpoint (402 with PAYMENT-REQUIRED header).",
      network: NETWORK,
      asset: ASSET,
      payTo: PAY_TO,
      endpoints: [
        { resource: `${origin}/api/jin/series`, price: "$0.01", free: false },
        { resource: `${origin}/api/jin/movers`, price: "$0.02", free: false },
        { resource: `${origin}/api/jin/latest`, price: null, free: true },
      ],
    },
    { headers: corsHeaders() },
  );
};
