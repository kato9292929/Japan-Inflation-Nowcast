// 売り手ログ（エンドポイント ↔ tx 署名）。実証2（kato9292929/poc-dual-checkout）が $0.01 の支払いを
// JIN と OSD に振り分けるために読む（JIN と OSD は Solana の受取口座を共有していて、チェーンだけでは区別できない）。
// 形式は poc-dual-checkout の docs/seller-log.md: { tx_signature, endpoint, amount, time_utc }。
// 保存先は Upstash Redis（REST）。キーは JST の日付ごと（sales:YYYY-MM-DD）。
// 購入者を特定できる情報（IP・UA・支払い元）は保存しない。
//
// 「記録が無い」と「記録していなかった」を区別する。実証2は 404 を「その日のログが無い」
// （$0.01 は不明のまま）、配列を「その日のログがある」（ログに無い $0.01 は消去法で OSD）と読む。
// 記録を始める前の日に [] を返すと、その日の $0.01 がすべて OSD と確定してしまう。
// そこで記録の開始日（sales:since）を持ち、開始日の翌日以降だけを「ログがある日」として扱う。
// 開始日そのものは開始前の時間帯を含むので、ログがある日に数えない。

export type SaleRecord = { tx_signature: string; endpoint: string; amount: string; time_utc: string };

const KEY_PREFIX = "sales:";
const SINCE_KEY = `${KEY_PREFIX}since`;
const TTL_SEC = 60 * 60 * 24 * 400;
// KV が応答しないときに支払いの応答を道連れにしない上限。
const KV_TIMEOUT_MS = 2000;
const DAY_MS = 24 * 3600 * 1000;

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

export type SalesLookup =
  | { status: "ok"; rows: SaleRecord[] }
  | { status: "not_covered"; coveredFrom: string | null };

const nextDay = (date: string) => jstDate(new Date(Date.parse(`${date}T00:00:00+09:00`) + DAY_MS));

// その日のログを返す。ログがある日（開始日の翌日以降・今日まで・保持期間内）だけ配列を返し、
// それ以外は not_covered（実証2には 404 として見せる）。記録が0件の「ログがある日」は []。
//
// 開始日は、口が初めて認証付きで読まれた日（JST）とする。読み取りと記録は同じデプロイに
// 載っているので、その時点で記録も動いている。SET NX なので最初の1回だけが残る。
export async function readSales(date: string, now: Date = new Date()): Promise<SalesLookup> {
  const today = jstDate(now);
  const [, since, rows] = (await pipeline([
    ["SET", SINCE_KEY, today, "NX"],
    ["GET", SINCE_KEY],
    ["LRANGE", KEY_PREFIX + date, 0, -1],
  ])) as [unknown, string | null, string[] | null];

  const coveredFrom = since ? nextDay(since) : null;
  const oldest = jstDate(new Date(now.getTime() - TTL_SEC * 1000));
  if (!coveredFrom || date < coveredFrom || date > today || date < oldest) {
    return { status: "not_covered", coveredFrom };
  }
  return { status: "ok", rows: (rows ?? []).map((r) => JSON.parse(r) as SaleRecord) };
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
