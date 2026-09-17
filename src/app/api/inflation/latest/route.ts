import { getInflationLatest } from "@/lib/inflation-data";
import { corsHeaders, corsPreflight } from "@/lib/x402-route";
import { NextResponse } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET() {
  try {
    return NextResponse.json(await getInflationLatest(), { headers: corsHeaders() });
  } catch {
    return NextResponse.json({ error: "inflation_data_unavailable" }, { status: 503, headers: corsHeaders() });
  }
}
export const OPTIONS = () => corsPreflight();
