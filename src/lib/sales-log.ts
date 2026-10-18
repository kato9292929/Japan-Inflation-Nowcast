// 売り手ログ（エンドポイント ↔ tx 署名）。実証2（kato9292929/poc-dual-checkout）が $0.01 の支払いを
// JIN と OSD に振り分けるために読む（JIN と OSD は Solana の受取口座を共有していて、チェーンだけでは区別できない）。
// 形式は poc-dual-checkout の docs/seller-log.md: { tx_signature, endpoint, amount, time_utc }。
// 保存先は Upstash Redis（REST）。キーは JST の日付ごと（sales:YYYY-MM-DD）。
// 購入者を特定できる情報（IP・UA・支払い元）は保存しない。
//
// 記録が無い日は [] を返す。記録を始める前の日と区別しないので、消去法に使ってよい日かどうかは
// 読み手（poc-dual-checkout の config/site.json の usdc.seller_log_since）が決める。

export type SaleRecord = { tx_signature: string; endpoint: string; amount: string; time_utc: string };

const KEY_PREFIX = "sales:";
const TTL_SEC = 60 * 60 * 24 * 400;
// KV が応答しないときに支払いの応答を道連れにしない上限。
const KV_TIMEOUT_MS = 2000;

function kv() {
  const url = process.env.SALES_LOG_KV_REST_URL;
  const token = process.env.SALES_LOG_KV_REST_TOKEN;
  return url && token ? { url: url.replace(/\/$/, ""), token } : null;
}

export function jstDate(d: Date): string {
  return new Date(d.getTime() + 9 * 3600 * 1000).toISOString().slice(0, 10);
}

// "$0.02" → "20000"（USDC の最小単位）
export function priceToAtomic(price: string): string {
  const m = /^\$?(\d+)(?:\.(\d{1,6}))?$/.exec(price.trim());
  if (!m) throw new Error(`bad price: ${price}`);
  return String(BigInt(m[1]) * 1_000_000n + BigInt((m[2] ?? "").padEnd(6, "0") || "0"));
}

async function pipeline(commands: (string | number)[][]): Promise<unknown[]> {
  const c = kv();
  if (!c) throw new Error("SALES_LOG_KV_REST_URL / SALES_LOG_KV_REST_TOKEN が未設定");
  const res = await fetch(`${c.url}/pipeline`, {
    method: "POST",
    headers: { authorization: `Bearer ${c.token}`, "content-type": "application/json" },
    body: JSON.stringify(commands),
    signal: AbortSignal.timeout(KV_TIMEOUT_MS),
  });
  if (!res.ok) throw new Error(`sales log kv: HTTP ${res.status}`);
  return ((await res.json()) as { result: unknown }[]).map((r) => r.result);
}

// settle に成功した支払いを1件記録する。保存先が未設定なら何もしない（JIN の応答は止めない）
export async function recordSale(rec: SaleRecord): Promise<void> {
  if (!kv()) return;
  const key = KEY_PREFIX + jstDate(new Date(rec.time_utc));
  await pipeline([
    ["RPUSH", key, JSON.stringify(rec)],
    ["EXPIRE", key, TTL_SEC],
  ]);
}

// その日の記録を返す。記録が無ければ []。
export async function readSales(date: string): Promise<SaleRecord[]> {
  const [rows] = (await pipeline([["LRANGE", KEY_PREFIX + date, 0, -1]])) as [string[] | null];
  return (rows ?? []).map((r) => JSON.parse(r) as SaleRecord);
}

// PAYMENT-RESPONSE（base64 の JSON）から tx 署名を取り出す。成功していなければ null
export function settledTx(header: string | null): string | null {
  if (!header) return null;
  try {
    const s = JSON.parse(Buffer.from(header, "base64").toString("utf8")) as { success?: boolean; transaction?: string };
    return s.success && s.transaction ? s.transaction : null;
  } catch {
    return null;
  }
}
