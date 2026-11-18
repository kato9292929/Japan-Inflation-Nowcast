import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { httpBinding, requestHash } from "@/lib/lnbtc";
import { signatureHeader } from "@/lib/lnbtc-facilitator";

// SDK 本体は実物。Solana の facilitator と lnbtc-facilitator（fetch）だけを合成応答にする。実決済はしない。
const facilitator = vi.hoisted(() => ({ getSupported: vi.fn(), verify: vi.fn(), settle: vi.fn() }));
const solana = "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp";
const recipient = "11111111111111111111111111111111";
const MAINNET = "lnbtc:000000000019d6689c085ae165831e93";
const PAY_TO = "0279be667ef9dcbbac55a06295ce870b07029bfcdb2dce28d959f2815b16f81798";
const SECRET = "k".repeat(40);
const INVOICE = "lnbc120n1ptestinvoice";
const PREIMAGE = "42".repeat(32);
const PAYMENT_HASH = "7b9d9c3f8d3c2b4b6a3b9f5d1b2f6d8a0c1e4f7a9b2c5d8e1f4a7b0c3d6e9f2a"; // 形だけ（照合しない）

vi.mock("@/lib/x402-server", async () => {
  const { x402ResourceServer } = await import("@x402/core/server");
  const { registerExactSvmScheme } = await import("@x402/svm/exact/server");
  const x402Server = new x402ResourceServer([facilitator]);
  registerExactSvmScheme(x402Server);
  return { x402Server };
});

type Call = { path: string; body: Record<string, unknown>; signature: string | null };
let calls: Call[] = [];
let replies: Record<string, (body: Record<string, unknown>) => Response | Promise<Response>> = {};

beforeEach(() => {
  vi.resetModules();
  vi.clearAllMocks();
  calls = [];
  replies = {
    "/invoice": () => Response.json({ invoice: INVOICE }),
    "/settle": () => Response.json({ success: true, transaction: PAYMENT_HASH, network: MAINNET }),
    "/credits": () => Response.json({ success: true, recorded: true }),
    "/credits/claim": () => Response.json({ success: true, granted: false }),
  };
  vi.stubEnv("X402_RECIPIENT", recipient);
  vi.stubEnv("PUBLIC_BASE_URL", "https://jin.test");
  vi.stubEnv("LNBTC_ENABLED", "true");
  vi.stubEnv("LNBTC_FACILITATOR_URL", "https://lnbtc.test");
  vi.stubEnv("LNBTC_HMAC_KEY_ID", "jin-2026-11");
  vi.stubEnv("LNBTC_HMAC_SECRET", SECRET);
  vi.stubEnv("LNBTC_PAY_TO", PAY_TO);
  vi.stubEnv("LNBTC_NETWORK", "mainnet");
  facilitator.getSupported.mockResolvedValue({
    kinds: [{ x402Version: 2, scheme: "exact", network: solana, extra: { feePayer: recipient } }],
    extensions: [], signers: { [solana]: [recipient] },
  });
  vi.stubGlobal("fetch", vi.fn(async (input: string | URL, init?: RequestInit) => {
    const url = new URL(String(input));
    expect(url.origin).toBe("https://lnbtc.test");
    const body = JSON.parse(String(init?.body ?? "{}")) as Record<string, unknown>;
    const signature = new Headers(init?.headers).get("x-jin-signature");
    calls.push({ path: url.pathname, body, signature });
    return replies[url.pathname](body);
  }));
});
afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

const series = async () => (await import("@/app/api/jin/series/route")).GET;
const SERIES_URL = "https://jin.test/api/jin/series?from=2026-10-19";
const hashOf = (url: string) =>
  requestHash(httpBinding({ method: "GET", url, publicOrigin: "https://jin.test", body: null, boundHeaders: [] }));

const decode = (value: string | null) => JSON.parse(Buffer.from(value ?? "", "base64").toString("utf8"));
const encode = (value: unknown) => Buffer.from(JSON.stringify(value)).toString("base64");

function paid(url: string, accepted: Record<string, unknown>, preimage = PREIMAGE, extraHeaders: Record<string, string> = {}) {
  const payload = { x402Version: 2, resource: { url }, accepted, payload: { preimage } };
  return new NextRequest(url, { headers: { "payment-signature": encode(payload), ...extraHeaders } });
}

async function offer(url = SERIES_URL) {
  const res = await (await series())(new NextRequest(url));
  expect(res.status).toBe(402);
  return decode(res.headers.get("payment-required"));
}

it("署名は facilitator/auth.py と同じ値になる（Python で作った期待値）", () => {
  expect(
    signatureHeader("jin-2026-11", SECRET, { timestamp: 1700000000, method: "post", path: "/settle", body: '{"a":"日本"}' }),
  ).toBe("t=1700000000,k=jin-2026-11,v1=1747d5360c9b1d0bdbf302954e264ad15e51a6527805677e03d33020776aad7e");
});

it("無効のときは Solana だけで、lnbtc-facilitator に問い合わせない", async () => {
  vi.stubEnv("LNBTC_ENABLED", "false");
  const required = await offer();
  expect(required.accepts.map((a: { network: string }) => a.network)).toEqual([solana]);
  expect(calls).toEqual([]);
});

it("鍵が不完全なら lnbtc を出さない", async () => {
  vi.stubEnv("LNBTC_HMAC_SECRET", "short");
  const required = await offer();
  expect(required.accepts).toHaveLength(1);
  expect(calls).toEqual([]);
});

it("402 に lnbtc を 1 件足す。invoice は実リクエストのハッシュで 402 のたびに取る", async () => {
  const required = await offer();
  expect(required.x402Version).toBe(2);
  expect(required.accepts[0].network).toBe(solana);
  const lnbtc = required.accepts[1];
  expect(lnbtc).toEqual({
    scheme: "exact",
    network: MAINNET,
    asset: "BTC",
    amount: "12000",
    payTo: PAY_TO,
    maxTimeoutSeconds: 300,
    extra: {
      assetTransferMethod: "bolt11",
      paymentFlow: "upfront",
      requestBindingProfile: "http:1",
      requestBindingParams: { headers: [] },
      requestHash: hashOf(SERIES_URL),
      invoice: INVOICE,
    },
  });
  expect(calls).toHaveLength(1);
  expect(calls[0].path).toBe("/invoice");
  expect(calls[0].body).toEqual({ amount: "12000", descriptionHash: hashOf(SERIES_URL), expirySeconds: 300, network: MAINNET });
  expect(calls[0].signature).toMatch(/^t=\d+,k=jin-2026-11,v1=[0-9a-f]{64}$/);
});

it("movers は 24000 msat", async () => {
  const res = await (await import("@/app/api/jin/movers/route")).GET(new NextRequest("https://jin.test/api/jin/movers"));
  const required = decode(res.headers.get("payment-required"));
  expect(required.accepts[1].amount).toBe("24000");
});

it("invoice が取れなければ lnbtc を外して Solana だけで返す", async () => {
  replies["/invoice"] = () => Response.json({ success: false, errorReason: "invoice_issuance_failed" }, { status: 502 });
  expect((await offer()).accepts).toHaveLength(1);
  replies["/invoice"] = () => Promise.reject(new TypeError("fetch failed"));
  expect((await offer()).accepts).toHaveLength(1);
});

it("公開オリジンは設定値で固定する（Host や転送ヘッダに左右されない）", async () => {
  const res = await (await series())(
    new NextRequest("https://preview.vercel.test/api/jin/series?from=2026-10-19", {
      headers: { "x-forwarded-host": "evil.test", host: "evil.test" },
    }),
  );
  const lnbtc = decode(res.headers.get("payment-required")).accepts[1];
  expect(lnbtc.extra.requestHash).toBe(hashOf(SERIES_URL));
});

it("支払い済み: /settle が成功してからハンドラを実行し、PAYMENT-RESPONSE を付ける", async () => {
  const lnbtc = (await offer()).accepts[1];
  calls = [];
  const res = await (await series())(paid(SERIES_URL, lnbtc));
  expect(res.status).toBe(200);
  expect(decode(res.headers.get("payment-response"))).toEqual({ success: true, transaction: PAYMENT_HASH, network: MAINNET });
  expect(calls.map((c) => c.path)).toEqual(["/settle"]);
  expect(facilitator.verify).not.toHaveBeenCalled();
  expect(facilitator.settle).not.toHaveBeenCalled();
  const sent = calls[0].body as { paymentRequirements: { extra: Record<string, unknown> } };
  expect(sent.paymentRequirements.extra.requestHash).toBe(hashOf(SERIES_URL));
  expect(sent.paymentRequirements.extra.invoice).toBe(INVOICE);
});

it("リクエストハッシュは実行するリクエストから計算し直す（accepted の値は使わない）", async () => {
  const lnbtc = (await offer()).accepts[1];
  const forged = { ...lnbtc, extra: { ...lnbtc.extra, requestHash: "00".repeat(32) } };
  const other = "https://jin.test/api/jin/series?from=2026-01-01";
  calls = [];
  await (await series())(paid(other, forged));
  const sent = calls.find((c) => c.path === "/settle")!.body as { paymentRequirements: { extra: Record<string, unknown> } };
  expect(sent.paymentRequirements.extra.requestHash).toBe(hashOf(other));
});

it("payload.resource.url が実行する URL と違えば /settle を呼ばずに 402", async () => {
  const lnbtc = (await offer()).accepts[1];
  const payload = { x402Version: 2, resource: { url: "https://jin.test/api/jin/movers" }, accepted: lnbtc, payload: { preimage: PREIMAGE } };
  calls = [];
  const res = await (await series())(new NextRequest(SERIES_URL, { headers: { "payment-signature": encode(payload) } }));
  expect(res.status).toBe(402);
  expect(decode(res.headers.get("payment-required")).error).toBe("invalid_exact_lnbtc_request_mismatch");
  expect(calls.map((c) => c.path)).toEqual(["/invoice"]);
});

it("/settle が検証で落とせば、理由と新しい invoice を付けた 402", async () => {
  const lnbtc = (await offer()).accepts[1];
  replies["/settle"] = () =>
    Response.json({ success: false, errorReason: "invalid_exact_lnbtc_invoice_request_mismatch", transaction: "", network: MAINNET }, { status: 402 });
  const res = await (await series())(paid(SERIES_URL, lnbtc));
  expect(res.status).toBe(402);
  const required = decode(res.headers.get("payment-required"));
  expect(required.error).toBe("invalid_exact_lnbtc_invoice_request_mismatch");
  expect(required.accepts.map((a: { network: string }) => a.network)).toEqual([solana, MAINNET]);
});

it("duplicate_settlement はクレジットが無ければ 402、あれば 1 回だけ提供する", async () => {
  const lnbtc = (await offer()).accepts[1];
  replies["/settle"] = () => Response.json({ success: false, errorReason: "duplicate_settlement", transaction: "", network: MAINNET }, { status: 402 });
  let res = await (await series())(paid(SERIES_URL, lnbtc));
  expect(res.status).toBe(402);
  expect(decode(res.headers.get("payment-required")).error).toBe("duplicate_settlement");

  replies["/credits/claim"] = () => Response.json({ success: true, granted: true });
  calls = [];
  res = await (await series())(paid(SERIES_URL, lnbtc));
  expect(res.status).toBe(200);
  const claim = calls.find((c) => c.path === "/credits/claim")!;
  expect(claim.body.resource).toBe("https://jin.test/api/jin/series");
  expect(String(claim.body.consumptionKey)).toMatch(new RegExp(`^${MAINNET}:[0-9a-f]{64}$`));
});

it("消費後にハンドラが失敗したらクレジットに記録して 503", async () => {
  const route = await import("@/lib/x402-route");
  const failing = route.withSolanaOnlyPaywall(() => { throw new Error("upstream down"); }, {
    price: "$0.01", description: "test", resourcePath: "/api/jin/series",
  });
  const lnbtc = (await offer()).accepts[1];
  calls = [];
  const res = await failing(paid(SERIES_URL, lnbtc));
  expect(res.status).toBe(503);
  expect(calls.map((c) => c.path)).toEqual(["/settle", "/credits"]);
  expect(calls[1].body).toEqual({
    consumptionKey: `${MAINNET}:${PAYMENT_HASH}`, resource: "https://jin.test/api/jin/series", reason: "handler_error",
  });
});

it("/settle に届かなければ 503（消費していないので同じ証明で再送できる）", async () => {
  const lnbtc = (await offer()).accepts[1];
  replies["/settle"] = () => Promise.reject(new TypeError("fetch failed"));
  const res = await (await series())(paid(SERIES_URL, lnbtc));
  expect(res.status).toBe(503);
  expect(await res.json()).toEqual({ error: "lnbtc_settlement_unavailable" });
});

it("network が設定と違う lnbtc の支払いは /settle を呼ばずに 402", async () => {
  const lnbtc = (await offer()).accepts[1];
  calls = [];
  const res = await (await series())(paid(SERIES_URL, { ...lnbtc, network: "lnbtc:000000000933ea01ad0ee984209779ba" }));
  expect(res.status).toBe(402);
  expect(calls.map((c) => c.path)).toEqual(["/invoice"]);
});
