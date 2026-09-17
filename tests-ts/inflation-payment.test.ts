import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

// SDK本体は実物。外部facilitatorだけを合成応答に置き換え、実決済は行わない。
const facilitator = vi.hoisted(() => ({
  getSupported: vi.fn(), verify: vi.fn(), settle: vi.fn(),
}));
const network = "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp";
const recipient = "11111111111111111111111111111111";

vi.mock("@/lib/x402-server", async () => {
  const { x402ResourceServer } = await import("@x402/core/server");
  const { registerExactSvmScheme } = await import("@x402/svm/exact/server");
  const x402Server = new x402ResourceServer([facilitator]);
  registerExactSvmScheme(x402Server);
  return { x402Server };
});

beforeEach(() => {
  vi.resetModules();
  vi.clearAllMocks();
  vi.stubEnv("X402_RECIPIENT", recipient);
  vi.stubEnv("PUBLIC_BASE_URL", "https://inflation.test/");
  vi.stubEnv("INFLATION_X402_ENABLED", "false");
  facilitator.getSupported.mockResolvedValue({
    kinds: [{ x402Version: 2, scheme: "exact", network, extra: { feePayer: recipient } }],
    extensions: [], signers: { [network]: [recipient] },
  });
  facilitator.verify.mockResolvedValue({ isValid: true, payer: recipient });
  facilitator.settle.mockResolvedValue({ success: true, payer: recipient, network, transaction: "合成テスト" });
});
afterEach(() => vi.unstubAllEnvs());

async function load() {
  return {
    route: await import("@/app/api/inflation/[country]/route"),
    latest: await import("@/app/api/inflation/latest/route"),
    discovery: await import("@/app/.well-known/x402.json/route"),
  };
}

const request = (country = "jp", headers?: HeadersInit) =>
  new NextRequest(`https://inflation.test/api/inflation/${country}`, { headers });
const context = (country = "jp") => ({ params: Promise.resolve({ country }) });

it("既定無料では決済通信せず、discoveryは設定価格と現在の無料状態を分ける", async () => {
  delete process.env.INFLATION_X402_ENABLED;
  const { route, discovery } = await load();
  expect((await route.GET(request(), context())).status).toBe(200);
  const body = await (await discovery.GET(new Request("https://proxy.test/.well-known/x402.json"))).json();
  expect(body.payTo).toBe(recipient);
  expect(body.endpoints.filter((e: { resource: string }) => e.resource.includes("/api/inflation/"))).toEqual([
    { resource: "https://inflation.test/api/inflation/latest", price: null, free: true },
    ...["jp", "kr", "sg"].map((country) => ({
      resource: `https://inflation.test/api/inflation/${country}`,
      price: null, configured_price: "$0.01", free: true,
    })),
  ]);
  expect(facilitator.getSupported).not.toHaveBeenCalled();
});

it("有料時のnative v2 402はdiscoveryと宛先・価格・USDC・リソースが一致する", async () => {
  vi.stubEnv("INFLATION_X402_ENABLED", "true");
  const { route, discovery } = await load();
  const body = await (await discovery.GET(new Request("https://proxy.test/.well-known/x402.json"))).json();
  for (const country of ["jp", "kr", "sg"]) {
    const response = await route.GET(request(country), context(country));
    expect(response.status).toBe(402);
    const header = response.headers.get("PAYMENT-REQUIRED");
    expect(header).toBeTruthy();
    const payment = JSON.parse(Buffer.from(header!, "base64").toString());
    expect(payment.x402Version).toBe(2);
    expect(payment.accepts).toHaveLength(1);
    const leg = payment.accepts[0];
    expect(leg.payTo).toBe(body.payTo);
    expect(leg.network).toBe(body.network);
    expect(leg.asset).toBe(body.asset);
    expect(leg.amount).toBe("10000");
    const advertised = body.endpoints.find((e: { resource: string }) => e.resource.endsWith(`/inflation/${country}`));
    expect(advertised).toMatchObject({ price: "$0.01", configured_price: "$0.01", free: false });
    expect(payment.resource.url).toBe(advertised.resource);
    expect(response.headers.get("access-control-allow-origin")).toBe("*");
    expect(response.headers.get("access-control-expose-headers")).toContain("PAYMENT-REQUIRED");
  }
  expect(facilitator.verify).not.toHaveBeenCalled();
  expect(facilitator.settle).not.toHaveBeenCalled();
});

it("有料設定でもlatest・OPTIONS・非対応国は決済初期化なし", async () => {
  vi.stubEnv("INFLATION_X402_ENABLED", "true");
  const { route, latest } = await load();
  expect((await latest.GET()).status).toBe(200);
  expect(route.OPTIONS().status).toBe(204);
  expect(route.OPTIONS().headers.get("access-control-allow-headers")).toContain("PAYMENT-SIGNATURE");
  expect((await route.GET(request("us"), context("us"))).status).toBe(404);
  expect(facilitator.getSupported).not.toHaveBeenCalled();
});

it("SDKによる検証・精算後に国別データを返す（合成決済）", async () => {
  vi.stubEnv("INFLATION_X402_ENABLED", "true");
  const { route } = await load();
  const challenge = await route.GET(request(), context());
  const payment = JSON.parse(Buffer.from(challenge.headers.get("PAYMENT-REQUIRED")!, "base64").toString());
  const signature = Buffer.from(JSON.stringify({
    x402Version: 2, resource: payment.resource, accepted: payment.accepts[0],
    payload: { transaction: "合成テスト" },
  })).toString("base64");
  const response = await route.GET(request("jp", { "PAYMENT-SIGNATURE": signature }), context());
  expect(response.status).toBe(200);
  expect((await response.json()).country).toBe("jp");
  expect(facilitator.verify).toHaveBeenCalledTimes(1);
  expect(facilitator.settle).toHaveBeenCalledTimes(1);
  expect(response.headers.get("PAYMENT-RESPONSE")).toBeTruthy();
});

it("facilitator障害は無料へフォールバックせず503", async () => {
  vi.stubEnv("INFLATION_X402_ENABLED", "true");
  facilitator.getSupported.mockRejectedValue(new Error("合成通信障害"));
  const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
  try {
    const { route } = await load();
    const response = await route.GET(request(), context());
    expect(response.status).toBe(503);
    expect(await response.json()).toEqual({ error: "payment_service_unavailable" });
    expect(response.headers.get("access-control-allow-origin")).toBe("*");
    expect(facilitator.settle).not.toHaveBeenCalled();
  } finally {
    warn.mockRestore();
  }
});
