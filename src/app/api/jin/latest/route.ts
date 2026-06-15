// GET /api/jin/latest — 無料・CORS open。最新観測日の指数（観測値のみ）。
import { getJinLatest } from "@/lib/jin-data";
import { corsHeaders } from "@/lib/x402";
import { corsPreflight } from "@/lib/x402-route";

export const dynamic = "force-static";

export const GET = () => Response.json(getJinLatest(), { headers: corsHeaders() });
export const OPTIONS = () => corsPreflight();
