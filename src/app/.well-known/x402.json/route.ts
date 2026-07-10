// x402 discovery。有料2本（series, movers）を v1+v2 併記の accepts で列挙。
// feePayer は facilitator /supported から動的取得するため force-static にせず動的化する
// （feePayer はローテーションするので焼き込むと実物とズレる）。resource は実測形どおりフル URL。
// description は ASCII のみ（非 Latin1 のエンコード事故を避ける）。
import { buildAccepts, X402_VERSION } from "@/lib/x402";

export const dynamic = "force-dynamic";

const SERIES = {
  price: "$0.01",
  description: "JIN daily food index series (excl/incl, matched SKU count)",
  resourcePath: "/api/jin/series",
};
const MOVERS = {
  price: "$0.02",
  description: "JIN daily inflation nowcast movers (per-day mover SKUs vs base, promo tags)",
  resourcePath: "/api/jin/movers",
};

export const GET = async (req: Request) => {
  const origin = new URL(req.url).origin;
  return Response.json({
    x402Version: X402_VERSION,
    source: "japan-inflation-nowcast",
    note: "observation data; not official CPI; not a forecast",
    endpoints: [
      {
        resource: SERIES.resourcePath,
        accepts: await buildAccepts(SERIES, `${origin}${SERIES.resourcePath}`),
      },
      {
        resource: MOVERS.resourcePath,
        accepts: await buildAccepts(MOVERS, `${origin}${MOVERS.resourcePath}`),
      },
    ],
  });
};
