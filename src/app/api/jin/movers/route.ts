// GET /api/jin/movers — $0.02・Solana paywall。指定日（既定は最新日）の mover SKU。
// promo_tag は観測事実のみ。確率・予測は含めない。
import { getJinMovers } from "@/lib/jin-data";
import { corsPreflight, withSolanaOnlyPaywall } from "@/lib/x402-route";

export const GET = withSolanaOnlyPaywall(
  (req: Request) => {
    const date = new URL(req.url).searchParams.get("date");
    return Response.json(getJinMovers(date));
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
