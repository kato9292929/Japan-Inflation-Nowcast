// GET /api/jin/movers — $0.02・Solana paywall（native withX402）。指定日（既定は最新日）の mover SKU。
// promo_tag は観測事実のみ。確率・予測は含めない。
import { getJinMovers } from "@/lib/jin-data";
import { corsPreflight, withSolanaOnlyPaywall } from "@/lib/x402-route";
import { NextResponse, type NextRequest } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export const GET = withSolanaOnlyPaywall(
  (req: NextRequest) => {
    const date = new URL(req.url).searchParams.get("date");
    return NextResponse.json(getJinMovers(date));
  },
  {
    price: "$0.02",
    description:
      "JIN daily inflation nowcast movers: per-day mover SKUs vs base date, with promo tags. " +
      "Single-store observation, not a forecast.",
    resourcePath: "/api/jin/movers",
  },
);

export const OPTIONS = () => corsPreflight();
