// x402 discovery。有料2本（series, movers）を静的 v1 leg で列挙。
// latest は無料なので載せない（README/landing に記載）。
// feePayer は facilitator /supported から動的取得するため force-static にせず動的化する
// （feePayer はローテーションするので焼き込むと実物とズレる）。accepts の他値は静的。
import { buildAcceptsBoth, X402_VERSION } from "@/lib/x402";

export const dynamic = "force-dynamic";

const SERIES = {
  price: "$0.01",
  description:
    "Japan Inflation Nowcast — daily food index series (excl/incl, matched SKU count).",
  resourcePath: "/api/jin/series",
};
const MOVERS = {
  price: "$0.02",
  description: "Japan Inflation Nowcast — per-day mover SKUs vs base date, with promo tags.",
  resourcePath: "/api/jin/movers",
};

export const GET = async () =>
  Response.json({
    x402Version: X402_VERSION,
    source: "japan-inflation-nowcast",
    note: "observation data; not official CPI; not a forecast",
    endpoints: [
      { resource: SERIES.resourcePath, accepts: await buildAcceptsBoth(SERIES) },
      { resource: MOVERS.resourcePath, accepts: await buildAcceptsBoth(MOVERS) },
    ],
  });
