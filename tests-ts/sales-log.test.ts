import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

// 売り手ログ（poc-dual-checkout の docs/seller-log.md）。外部 facilitator と KV（Upstash REST）だけを合成にする。
const facilitator = vi.hoisted(() => ({ getSupported: vi.fn(), verify: vi.fn(), settle: vi.fn() }));
const network = "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp";
const recipient = "11111111111111111111111111111111";
const TOKEN = "t".repeat(40);

vi.mock("@/lib/x402-server", async () => {
  const { x402ResourceServer } = await import("@x402/core/server");
  const { registerExactSvmScheme } = await import("@x402/svm/exact/server");
  const x402Server = new x402ResourceServer([facilitator]);
  registerExactSvmScheme(x402Server);
  return { x402Server };
});

// 合成 KV：RPUSH / EXPIRE / LRANGE だけ
const lists = new Map<string, string[]>();
const kvCalls: unknown[][] = [];
const realFetch = globalThis.fetch;

const today = () => new Date(Date.now() + 9 * 3600 * 1000).toISOString().slice(0, 10);

beforeEach(() => {
  vi.resetModules();
  vi.clearAllMocks();
  lists.clear();
  kvCalls.length = 0;
  vi.stubEnv("X402_RECIPIENT", recipient);
  vi.stubEnv("PUBLIC_BASE_URL", "https://jin.test/");
  vi.stubEnv("SALES_LOG_KV_REST_URL", "https://kv.test");
  vi.stubEnv("SALES_LOG_KV_REST_TOKEN", "kvtoken");
  vi.stubEnv("SELLER_LOG_TOKEN", TOKEN);
  facilitator.getSupported.mockResolvedValue({
    kinds: [{ x402Version: 2, scheme: "exact", network, extra: { feePayer: recipient } }],
    extensions: [], signers: { [network]: [recipient] },
  });
  facilitator.verify.mockResolvedValue({ isValid: true, payer: recipient });
  facilitator.settle.mockResolvedValue({ success: true, payer: recipient, network, transaction: "TXSIG1" });
  globalThis.fetch = (async (url: string | URL, init?: RequestInit) => {
    if (!String(url).startsWith("https://kv.test/")) return realFetch(url, init);
    const cmds = JSON.parse(String(init!.body)) as (string | number)[][];
    const out = cmds.map(([op, key, ...rest]) => {
      kvCalls.push([op, key, ...rest]);
      const k = String(key);
      if (op === "RPUSH") return { result: lists.set(k, [...(lists.get(k) ?? []), String(rest[0])]).get(k)!.length };
      if (op === "LRANGE") return { result: lists.get(k) ?? [] };
      return { result: 1 };
    });
    return new Response(JSON.stringify(out), { status: 200 });
  }) as typeof fetch;
});
afterEach(() => {
  vi.unstubAllEnvs();
  globalThis.fetch = realFetch;
});

async function payMovers() {
  const route = await import("@/app/api/jin/movers/route");
  const req = (headers?: HeadersInit) => new NextRequest("https://jin.test/api/jin/movers", { headers });
  const challenge = await route.GET(req());
  const payment = JSON.parse(Buffer.from(challenge.headers.get("PAYMENT-REQUIRED")!, "base64").toString());
  const signature = Buffer.from(JSON.stringify({
    x402Version: 2, resource: payment.resource, accepted: payment.accepts[0], payload: { transaction: "合成テスト" },
  })).toString("base64");
  return route.GET(req({ "PAYMENT-SIGNATURE": signature }));
}

// auth に null を渡すと Authorization ヘッダを付けない（undefined だと既定値が効くため）。
async function sales(date: string, auth: string | null = `Bearer ${TOKEN}`) {
  const route = await import("@/app/sales/[date]/route");
  return route.GET(
    new NextRequest(`https://jin.test/sales/${date}`, { headers: auth ? { authorization: auth } : {} }),
    { params: Promise.resolve({ date }) },
  );
}

// --- 記録（パッチ由来） ---------------------------------------------------- //
it("settle に成功した支払いを JST の日付ごとに1件記録する（エンドポイント・金額・tx 署名）", async () => {
  const res = await payMovers();
  expect(res.status).toBe(200);
  const keys = [...lists.keys()];
  expect(keys).toHaveLength(1);
  expect(keys[0]).toMatch(/^sales:\d{4}-\d{2}-\d{2}$/);
  const rec = JSON.parse(lists.get(keys[0])![0]);
  expect(rec).toMatchObject({ tx_signature: "TXSIG1", endpoint: "https://jin.test/api/jin/movers", amount: "20000" });
  expect(Object.keys(rec).sort()).toEqual(["amount", "endpoint", "time_utc", "tx_signature"]);
  expect(kvCalls.some(([op]) => op === "EXPIRE")).toBe(true);
});

it("未払い（402）と settle 失敗は記録しない", async () => {
  const route = await import("@/app/api/jin/movers/route");
  expect((await route.GET(new NextRequest("https://jin.test/api/jin/movers"))).status).toBe(402);
  facilitator.settle.mockResolvedValue({ success: false, errorReason: "合成失敗", network, transaction: "" });
  await payMovers().catch(() => null);
  expect(lists.size).toBe(0);
});

it("記録に失敗しても JIN の応答は返す（KV が 500）", async () => {
  vi.stubEnv("SALES_LOG_KV_REST_URL", "https://kv-down.test");
  globalThis.fetch = (async (url: string | URL, init?: RequestInit) =>
    String(url).startsWith("https://kv-down.test/") ? new Response("", { status: 500 }) : realFetch(url, init)) as typeof fetch;
  const err = vi.spyOn(console, "error").mockImplementation(() => {});
  try {
    expect((await payMovers()).status).toBe(200);
    expect(err).toHaveBeenCalled();
  } finally {
    err.mockRestore();
  }
});

it("priceToAtomic と jstDate", async () => {
  const { priceToAtomic, jstDate } = await import("@/lib/sales-log");
  expect(priceToAtomic("$0.02")).toBe("20000");
  expect(priceToAtomic("$0.01")).toBe("10000");
  expect(priceToAtomic("$1")).toBe("1000000");
  expect(jstDate(new Date("2026-10-17T15:00:00Z"))).toBe("2026-10-18");
});

// --- 追加：記録の失敗が支払いの応答を止めない ------------------------------- //
it("記録に失敗しても JIN の応答は返す（KV が応答しない）", async () => {
  vi.stubEnv("SALES_LOG_KV_REST_URL", "https://kv-hang.test");
  globalThis.fetch = (async (url: string | URL, init?: RequestInit) => {
    if (!String(url).startsWith("https://kv-hang.test/")) return realFetch(url, init);
    // 応答を返さず、タイムアウトの中断だけを待つ。
    return new Promise<Response>((_, reject) =>
      init?.signal?.addEventListener("abort", () => reject(init.signal!.reason)),
    );
  }) as typeof fetch;
  const err = vi.spyOn(console, "error").mockImplementation(() => {});
  try {
    const res = await payMovers();
    expect(res.status).toBe(200);
    expect(err).toHaveBeenCalled();
  } finally {
    err.mockRestore();
  }
}, 10_000);

it("KV が未設定なら記録せず、支払いの応答はそのまま返す", async () => {
  vi.stubEnv("SALES_LOG_KV_REST_URL", "");
  expect((await payMovers()).status).toBe(200);
  expect(kvCalls).toHaveLength(0);
});

// --- GET /sales/:date（パッチ由来を「記録が無い日は []」に直したもの） -------- //
it("GET /sales/:date は Bearer が一致したときだけ、その日の記録を返す", async () => {
  await payMovers();
  const date = [...lists.keys()][0].slice("sales:".length);
  expect((await sales(date, null)).status).toBe(401);
  expect((await sales(date, "Bearer wrong")).status).toBe(401);
  const ok = await sales(date);
  expect(ok.status).toBe(200);
  expect((await ok.json())[0].tx_signature).toBe("TXSIG1");
  expect((await sales("bad")).status).toBe(400);
  vi.stubEnv("SELLER_LOG_TOKEN", "short");
  expect((await sales(date)).status).toBe(404); // 短いトークンでは口を開けない
});

// --- 追加：GET /sales/:date ---------------------------------------------- //
it("トークン無し・不一致・Bearer 以外は 401（記録がある日でも中身を返さない）", async () => {
  await payMovers();
  for (const auth of [null, "Bearer wrong", `Bearer ${TOKEN}x`, `Basic ${TOKEN}`, TOKEN]) {
    const res = await sales(today(), auth);
    expect(res.status).toBe(401);
    expect(await res.json()).toEqual({ error: "unauthorized" });
  }
});

it("トークン一致・その日の記録が無ければ []", async () => {
  await payMovers(); // 今日の記録はあるが、別の日には無い
  for (const date of ["2000-01-01", "2099-12-31"]) {
    const res = await sales(date);
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual([]);
  }
});

it("KV 障害は 502（[] と取り違えない）", async () => {
  vi.stubEnv("SALES_LOG_KV_REST_URL", "https://kv-down.test");
  globalThis.fetch = (async () => new Response("", { status: 500 })) as typeof fetch;
  const err = vi.spyOn(console, "error").mockImplementation(() => {});
  try {
    expect((await sales(today())).status).toBe(502);
  } finally {
    err.mockRestore();
  }
});
