import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import {
  appendTransactionMessageInstruction, compileTransaction, createTransactionMessage, generateKeyPairSigner,
  getBase64EncodedWireTransaction, partiallySignTransaction, pipe, setTransactionMessageFeePayer,
  setTransactionMessageLifetimeUsingBlockhash, type Address, type Blockhash,
} from "@solana/kit";

// Delivery Receipt: 合成決済で /api/jin/series を買い、レシートを検証し、決済なしで再取得できることを見る。
// facilitator は合成応答、支払いの tx は使い捨ての鍵でその場で署名したもの（送信しない）。
const facilitator = vi.hoisted(() => ({ getSupported: vi.fn(), verify: vi.fn(), settle: vi.fn() }));
const network = "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp";
const recipient = "11111111111111111111111111111111";
const txId = "5VERv8NMvzbJMEkV8xnrLkEaWRtSz9CosKDYjCJjBRnbJLgp8uirBgmQpjKhoR4tjF3ZpRzrFmBV6UjKdiSZkQUW";

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
  vi.stubEnv("PUBLIC_BASE_URL", "https://jin.test");
  facilitator.getSupported.mockResolvedValue({
    kinds: [{ x402Version: 2, scheme: "exact", network, extra: { feePayer: recipient } }],
    extensions: [], signers: { [network]: [recipient] },
  });
  facilitator.verify.mockResolvedValue({ isValid: true, payer: recipient });
  facilitator.settle.mockResolvedValue({ success: true, payer: recipient, network, transaction: txId });
});
afterEach(() => vi.unstubAllEnvs());

async function signedTx(): Promise<string> {
  const payer = await generateKeyPairSigner();
  const msg = pipe(
    createTransactionMessage({ version: 0 }),
    (m) => setTransactionMessageFeePayer(recipient as Address, m),
    (m) => setTransactionMessageLifetimeUsingBlockhash({ blockhash: "11111111111111111111111111111111" as Blockhash, lastValidBlockHeight: 0n }, m),
    (m) => appendTransactionMessageInstruction(
      { programAddress: "MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr" as Address, accounts: [{ address: payer.address, role: 3 }], data: new Uint8Array([1]) }, m),
  );
  const tx = await partiallySignTransaction([payer.keyPair], compileTransaction(msg));
  return getBase64EncodedWireTransaction(tx);
}

it("有料の 200 にレシートが付き、検証が通る。再取得は決済なしで同じ本文を返す", async () => {
  const route = await import("@/app/api/jin/series/route");
  const wk = await import("@/app/.well-known/x402-receipt.json/route");
  const { verifyReceipt, refetch, parseWellKnown } = await import("@/lib/delivery-receipt/verify");
  const url = "https://jin.test/api/jin/series";

  const challenge = await route.GET(new NextRequest(url));
  expect(challenge.status).toBe(402);
  const payment = JSON.parse(Buffer.from(challenge.headers.get("PAYMENT-REQUIRED")!, "base64").toString());
  const signature = Buffer.from(JSON.stringify({
    x402Version: 2, resource: payment.resource, accepted: payment.accepts[0], payload: { transaction: await signedTx() },
  })).toString("base64");

  const paid = await route.GET(new NextRequest(url, { headers: { "PAYMENT-SIGNATURE": signature } }));
  expect(paid.status).toBe(200);
  const body = new Uint8Array(await paid.arrayBuffer());
  const wellKnown = parseWellKnown(await (await wk.GET()).json());
  expect(wellKnown.keys).toHaveLength(1);
  const v = verifyReceipt({ header: paid.headers.get("X-Delivery-Receipt"), body, wellKnown, expect: { payment_id: txId, resource: url } });
  expect(v.ok).toBe(true);
  expect(paid.headers.get("access-control-expose-headers")).toContain("X-Delivery-Receipt");
  expect(facilitator.settle).toHaveBeenCalledTimes(1);

  // 再取得：元の支払いヘッダ＋X-Payment-Refetch。route を fetch の代わりに使う。
  const viaRoute = (async (input: RequestInfo | URL, init?: RequestInit) =>
    route.GET(new NextRequest(String(input), init as never))) as typeof fetch;
  const r = await refetch({ url, paymentHeaders: { "PAYMENT-SIGNATURE": signature }, paymentId: txId, wellKnown, fetch: viaRoute });
  expect(r.ok).toBe(true);
  if (r.ok) {
    expect(Buffer.from(r.body).equals(Buffer.from(body))).toBe(true);
    expect(r.receipt.delivery).toBe("refetch");
  }
  expect(facilitator.verify).toHaveBeenCalledTimes(1);
  expect(facilitator.settle).toHaveBeenCalledTimes(1);

  // 別の支払いヘッダでは再取得できない
  const other = Buffer.from(JSON.stringify({
    x402Version: 2, resource: payment.resource, accepted: payment.accepts[0], payload: { transaction: await signedTx() },
  })).toString("base64");
  const bad = await refetch({ url, paymentHeaders: { "PAYMENT-SIGNATURE": other }, paymentId: txId, wellKnown, fetch: viaRoute });
  expect(bad).toMatchObject({ ok: false, reason: "refetch_refused" });
});

it("RECEIPT_SIGNING_KEY が無ければ起動時に止まる", async () => {
  vi.stubEnv("RECEIPT_SIGNING_KEY", "");
  const { register } = await import("@/instrumentation");
  vi.stubEnv("NEXT_RUNTIME", "nodejs");
  await expect(register()).rejects.toThrow(/RECEIPT_SIGNING_KEY/);
});
