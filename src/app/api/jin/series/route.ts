// GET /api/jin/series — $0.01・Solana paywall（native withX402）。指数時系列（from/to クエリ）。
import { getJinSeries } from "@/lib/jin-data";
import { corsPreflight, withSolanaOnlyPaywall } from "@/lib/x402-route";
import { NextResponse, type NextRequest } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export const GET = withSolanaOnlyPaywall(
  (req: NextRequest) => {
    const q = new URL(req.url).searchParams;
    return NextResponse.json(getJinSeries(q.get("from"), q.get("to")));
  },
  {
    price: "$0.01",
    description:
      "JIN daily food index series (excl/incl, matched SKU count). " +
      "Single-store observation, not official CPI, not a forecast.",
    resourcePath: "/api/jin/series",
  },
);

export const OPTIONS = () => corsPreflight();
