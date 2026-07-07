// x402 discovery。有料2本（series, movers）を Solana leg 付きで列挙。
// latest は無料なので載せない（README/landing に記載）。
import { paymentRequirements, X402_VERSION } from "@/lib/x402";

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

export const GET = () =>
  Response.json({
    x402Version: X402_VERSION,
    source: "japan-inflation-nowcast",
    note: "observation data; not official CPI; not a forecast",
    endpoints: [
      { resource: SERIES.resourcePath, accepts: [paymentRequirements(SERIES)] },
      { resource: MOVERS.resourcePath, accepts: [paymentRequirements(MOVERS)] },
    ],
  });
