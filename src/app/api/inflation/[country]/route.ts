import { getInflation, isCountry, type Country } from "@/lib/inflation-data";
import { inflationPaymentsEnabled, INFLATION_PRICE } from "@/lib/inflation-payment";
import { corsHeaders, corsPreflight, withSolanaOnlyPaywall } from "@/lib/x402-route";
import { NextResponse, type NextRequest } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

async function serveCountry(country: Country) {
  try {
    return NextResponse.json(await getInflation(country), { headers: corsHeaders() });
  } catch {
    return NextResponse.json({ error: "inflation_data_unavailable" }, { status: 503, headers: corsHeaders() });
  }
}

const paidHandlers = new Map<Country, ReturnType<typeof withSolanaOnlyPaywall>>();

export async function GET(req: NextRequest, context: { params: Promise<{ country: string }> }) {
  const { country } = await context.params;
  if (!isCountry(country)) {
    return NextResponse.json({ error: "unsupported_country" }, { status: 404, headers: corsHeaders() });
  }
  if (!inflationPaymentsEnabled()) return serveCountry(country);
  try {
    // 無料時はwithX402の生成もfacilitatorへの初期化通信も行わない。
    let handler = paidHandlers.get(country);
    if (!handler) {
      handler = withSolanaOnlyPaywall(() => serveCountry(country), {
        price: INFLATION_PRICE,
        description: "公的CPIの最新保存値。日本はJIN店頭観測を併記。",
        resourcePath: `/api/inflation/${country}`,
      });
      paidHandlers.set(country, handler);
    }
    return await handler(req);
  } catch {
    return NextResponse.json({ error: "payment_service_unavailable" }, { status: 503, headers: corsHeaders() });
  }
}
export const OPTIONS = () => corsPreflight();
