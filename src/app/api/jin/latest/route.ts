// GET /api/jin/latest — 無料・CORS open。最新観測日の指数（観測値のみ）＋ passthrough_gap。
import { getJinLatest } from "@/lib/jin-data";
import { corsHeaders, corsPreflight } from "@/lib/x402-route";
import { NextResponse } from "next/server";

export const dynamic = "force-static";

export const GET = () => NextResponse.json(getJinLatest(), { headers: corsHeaders() });
export const OPTIONS = () => corsPreflight();
