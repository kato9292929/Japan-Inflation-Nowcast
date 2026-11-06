// 有料エンドポイントに x402 exact/lnbtc を足す。Solana の 402 と支払いは withX402 のまま。
//
// 未払い: withX402 が返した 402 の PAYMENT-REQUIRED（v2）の accepts に lnbtc を 1 件足す。
//   invoice はファシリテーターの /invoice から 402 のたびに取る。1 秒で取れなければ lnbtc を外す。
// 支払い済み: 支払いヘッダの accepted.network が lnbtc:* のときだけここで扱い、withX402 には渡さない。
//   リクエストハッシュは実行するリクエストから計算し直し（accepted.extra や invoice からは取らない）、
//   /settle が成功してからハンドラを実行する。upfront フローなので /verify は呼ばない。
//
// 公開 URL のオリジンは PUBLIC_BASE_URL で固定する。転送ヘッダ（Host・X-Forwarded-*）は見ない。

import { createHash } from "node:crypto";
import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";
import { ASSET, ASSET_TRANSFER_METHOD, httpBinding, PAYMENT_FLOW, requestHash, SCHEME } from "./lnbtc";
import { LNBTC_MAX_TIMEOUT_SECONDS, LNBTC_PRICES_MSAT, lnbtcConfig, type LnbtcConfig } from "./lnbtc-config";
import { claimCredit, recordCredit, requestInvoice, settlePayment } from "./lnbtc-facilitator";

const PAYMENT_HEADERS = ["payment-signature", "x-payment"] as const;
const HEX32 = /^[0-9a-f]{64}$/;

export type LnbtcRequirements = {
  scheme: string;
  network: string;
  asset: string;
  amount: string;
  payTo: string;
  maxTimeoutSeconds: number;
  extra: Record<string, unknown>;
};

type Bound = { url: string; hash: string };

/** 実行するリクエストの公開 URL とリクエストハッシュ。bound header は使わない。 */
export function bindRequest(req: Request, publicBaseUrl: string): Bound {
  const origin = new URL(publicBaseUrl).origin;
  const target = new URL(req.url);
  const url = `${origin}${target.pathname}${target.search}`;
  const binding = httpBinding({ method: req.method, url, publicOrigin: origin, body: null, boundHeaders: [] });
  return { url, hash: requestHash(binding) };
}

export function lnbtcRequirements(
  cfg: LnbtcConfig,
  amount: string,
  hash: string,
  invoice?: string,
): LnbtcRequirements {
  return {
    scheme: SCHEME,
    network: cfg.network,
    asset: ASSET,
    amount,
    payTo: cfg.payTo,
    maxTimeoutSeconds: LNBTC_MAX_TIMEOUT_SECONDS,
    extra: {
      assetTransferMethod: ASSET_TRANSFER_METHOD,
      paymentFlow: PAYMENT_FLOW,
      requestBindingProfile: "http:1",
      requestBindingParams: { headers: [] },
      requestHash: hash,
      ...(invoice === undefined ? {} : { invoice }),
    },
  };
}

function decodeBase64Json(value: string | null): Record<string, unknown> | null {
  if (!value) return null;
  try {
    const parsed = JSON.parse(Buffer.from(value.trim(), "base64").toString("utf8")) as unknown;
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? (parsed as Record<string, unknown>) : null;
  } catch {
    return null;
  }
}

const encodeBase64Json = (value: unknown) => Buffer.from(JSON.stringify(value), "utf8").toString("base64");

/** 支払いヘッダが lnbtc の支払いなら、その payload を返す。 */
export function lnbtcPaymentPayload(req: Request): Record<string, unknown> | null {
  for (const name of PAYMENT_HEADERS) {
    const payload = decodeBase64Json(req.headers.get(name));
    if (!payload) continue;
    const accepted = payload.accepted as Record<string, unknown> | undefined;
    if (accepted && typeof accepted.network === "string" && accepted.network.startsWith("lnbtc:")) return payload;
    return null;
  }
  return null;
}

/** withX402 の 402 に lnbtc の選択肢を足す。足せなければそのまま返す。 */
export async function appendLnbtcOffer(
  res: NextResponse,
  req: Request,
  resourcePath: string,
  publicBaseUrl: string,
  error?: string,
): Promise<NextResponse> {
  if (res.status !== 402) return res;
  const paymentRequired = decodeBase64Json(res.headers.get("payment-required"));
  if (!paymentRequired || !Array.isArray(paymentRequired.accepts)) return res;
  if (error) paymentRequired.error = error;
  const cfg = lnbtcConfig();
  const amount = LNBTC_PRICES_MSAT[resourcePath];
  if (cfg && amount) {
    const { hash } = bindRequest(req, publicBaseUrl);
    const invoice = await requestInvoice(cfg, {
      amount,
      descriptionHash: hash,
      expirySeconds: LNBTC_MAX_TIMEOUT_SECONDS,
    });
    if (invoice) paymentRequired.accepts.push(lnbtcRequirements(cfg, amount, hash, invoice));
  }
  res.headers.set("payment-required", encodeBase64Json(paymentRequired));
  return res;
}

const paymentHashOf = (preimage: unknown): string | null =>
  typeof preimage === "string" && HEX32.test(preimage)
    ? createHash("sha256").update(Buffer.from(preimage, "hex")).digest("hex")
    : null;

export type LnbtcPaidOptions = {
  resourcePath: string;
  publicBaseUrl: string;
  handler: (req: NextRequest) => Promise<NextResponse> | NextResponse;
  /** 支払いヘッダを外したリクエストで作り直した 402（lnbtc の新しい invoice 付き）。 */
  fresh402: (error: string) => Promise<NextResponse>;
};

/** lnbtc の支払い付きの再送を処理する。lnbtc の支払いでなければ null。 */
export async function handleLnbtcPayment(req: NextRequest, opts: LnbtcPaidOptions): Promise<NextResponse | null> {
  const payload = lnbtcPaymentPayload(req);
  if (!payload) return null;
  const cfg = lnbtcConfig();
  const amount = LNBTC_PRICES_MSAT[opts.resourcePath];
  if (!cfg || !amount) return opts.fresh402("unsupported_scheme");

  const accepted = payload.accepted as Record<string, unknown>;
  const acceptedExtra = (accepted.extra ?? {}) as Record<string, unknown>;
  const invoice = typeof acceptedExtra.invoice === "string" ? acceptedExtra.invoice : undefined;
  if (accepted.network !== cfg.network || !invoice) return opts.fresh402("invalid_exact_lnbtc_payload");

  // 実行するリクエストから計算し直す。accepted.extra.requestHash は使わない。
  const bound = bindRequest(req, opts.publicBaseUrl);
  const resource = payload.resource as Record<string, unknown> | undefined;
  if (resource && typeof resource.url === "string" && resource.url !== bound.url) {
    return opts.fresh402("invalid_exact_lnbtc_request_mismatch");
  }
  // invoice は署名済みで、ファシリテーターが description hash・金額・payTo・署名を確かめる。
  const required = lnbtcRequirements(cfg, amount, bound.hash, invoice);
  const reply = await settlePayment(cfg, payload, required);
  if (!reply || reply.status === 401 || reply.status === 429 || reply.status >= 500) {
    // 消費していないので、同じ証明で後から再送できる。
    return NextResponse.json({ error: "lnbtc_settlement_unavailable" }, { status: 503 });
  }

  const paymentHash = paymentHashOf((payload.payload as Record<string, unknown> | undefined)?.preimage);
  const consumptionKey = paymentHash ? `${cfg.network}:${paymentHash}` : null;
  const creditResource = `${opts.publicBaseUrl}${opts.resourcePath}`;

  if (reply.body.success === true && typeof reply.body.transaction === "string") {
    return serve(req, opts, cfg, {
      settle: { success: true, transaction: reply.body.transaction, network: cfg.network },
      consumptionKey: `${cfg.network}:${reply.body.transaction}`,
      creditResource,
    });
  }
  const reason = typeof reply.body.errorReason === "string" ? reply.body.errorReason : "settlement_failed";
  if (reason === "duplicate_settlement" && consumptionKey) {
    const granted = await claimCredit(cfg, { consumptionKey, resource: creditResource, reason: "redelivery" });
    if (granted) {
      return serve(req, opts, cfg, {
        settle: { success: true, transaction: paymentHash, network: cfg.network },
        consumptionKey,
        creditResource,
      });
    }
  }
  return opts.fresh402(reason);
}

async function serve(
  req: NextRequest,
  opts: LnbtcPaidOptions,
  cfg: LnbtcConfig,
  ctx: { settle: Record<string, unknown>; consumptionKey: string; creditResource: string },
): Promise<NextResponse> {
  let res: NextResponse | null = null;
  try {
    res = await opts.handler(req);
  } catch (e) {
    console.error("[lnbtc] ハンドラが失敗", e);
  }
  if (!res || res.status >= 500) {
    // 消費済みで提供できなかった。次の再送で 1 回だけ消費なしに出す。
    const recorded = await recordCredit(cfg, {
      consumptionKey: ctx.consumptionKey,
      resource: ctx.creditResource,
      reason: res ? `handler_status_${res.status}` : "handler_error",
    });
    return NextResponse.json(
      { error: "delivery_failed", credit_recorded: recorded, retry: "resend the same payment" },
      { status: 503 },
    );
  }
  res.headers.set("payment-response", encodeBase64Json(ctx.settle));
  return res;
}
