// GET /sales/:date — 売り手ログ（JST の日付ごと）。実証2（poc-dual-checkout）が読む。
// 認証は Authorization: Bearer <SELLER_LOG_TOKEN>（32文字以上。未設定・短すぎるときは口ごと閉じて 404）。
// その日の記録の配列を返す。記録が無い日は []。読み取り専用。
import { createHash, timingSafeEqual } from "node:crypto";
import { readSales } from "@/lib/sales-log";
import { NextResponse, type NextRequest } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const digest = (s: string) => createHash("sha256").update(s).digest();

export async function GET(req: NextRequest, ctx: { params: Promise<{ date: string }> }) {
  const expected = process.env.SELLER_LOG_TOKEN;
  if (!expected || expected.length < 32) return NextResponse.json({ error: "not_found" }, { status: 404 });
  const m = /^Bearer\s+(\S+)$/i.exec(req.headers.get("authorization") ?? "");
  if (!m || !timingSafeEqual(digest(m[1]), digest(expected))) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401, headers: { "www-authenticate": "Bearer" } });
  }
  const { date } = await ctx.params;
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) return NextResponse.json({ error: "date must be JST YYYY-MM-DD" }, { status: 400 });
  try {
    return NextResponse.json(await readSales(date), { headers: { "cache-control": "no-store" } });
  } catch (e) {
    console.error(e);
    return NextResponse.json({ error: "sales_log_unavailable" }, { status: 502 });
  }
}
