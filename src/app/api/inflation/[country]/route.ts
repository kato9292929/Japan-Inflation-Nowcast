import { getInflation, isCountry } from "@/lib/inflation-data";
import { corsHeaders, corsPreflight } from "@/lib/x402-route";
import { NextResponse, type NextRequest } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(_req: NextRequest, context: { params: Promise<{ country: string }> }) {
  const { country } = await context.params;
  if (!isCountry(country)) {
    return NextResponse.json({ error: "unsupported_country" }, { status: 404, headers: corsHeaders() });
  }
  try {
    return NextResponse.json(await getInflation(country), { headers: corsHeaders() });
  } catch {
    return NextResponse.json({ error: "inflation_data_unavailable" }, { status: 503, headers: corsHeaders() });
  }
}
export const OPTIONS = () => corsPreflight();
