// lnbtc-facilitator の HTTP クライアント。署名は facilitator/auth.py と同じ形:
//   X-JIN-Signature: t=<unix秒>,k=<鍵ID>,v1=<HMAC-SHA256(secret, "<t>\n<METHOD>\n<path>\n" + body) の 16 進>
// method と path を署名に含めるので、/settle 向けの署名を /credits/claim に投げ替えられない。

import { createHmac } from "node:crypto";
import { LNBTC_INVOICE_TIMEOUT_MS, LNBTC_SETTLE_TIMEOUT_MS, type LnbtcConfig } from "./lnbtc-config";

export function signatureHeader(
  keyId: string,
  secret: string,
  { timestamp, method, path, body }: { timestamp: number; method: string; path: string; body: string },
): string {
  const message = Buffer.concat([
    Buffer.from(`${timestamp}\n${method.toUpperCase()}\n${path}\n`, "utf8"),
    Buffer.from(body, "utf8"),
  ]);
  const digest = createHmac("sha256", secret).update(message).digest("hex");
  return `t=${timestamp},k=${keyId},v1=${digest}`;
}

export type FacilitatorReply = { status: number; body: Record<string, unknown> };

/** 署名付きで POST する。届かない・時間切れ・JSON でない応答は null。 */
async function post(
  cfg: LnbtcConfig,
  path: string,
  payload: unknown,
  timeoutMs: number,
  now: () => number = Date.now,
): Promise<FacilitatorReply | null> {
  const body = JSON.stringify(payload);
  const header = signatureHeader(cfg.keyId, cfg.secret, {
    timestamp: Math.floor(now() / 1000),
    method: "POST",
    path,
    body,
  });
  try {
    const res = await fetch(`${cfg.facilitatorUrl}${path}`, {
      method: "POST",
      headers: { "content-type": "application/json", "x-jin-signature": header },
      body,
      signal: AbortSignal.timeout(timeoutMs),
      redirect: "error",
    });
    const json = (await res.json()) as unknown;
    if (!json || typeof json !== "object") return null;
    return { status: res.status, body: json as Record<string, unknown> };
  } catch (e) {
    console.error(`[lnbtc] ${path} に届きません:`, e instanceof Error ? e.name : "unknown");
    return null;
  }
}

/** 402 のたびに新しい invoice を取る。失敗したら null（呼び出し側は lnbtc を外す）。 */
export async function requestInvoice(
  cfg: LnbtcConfig,
  req: { amount: string; descriptionHash: string; expirySeconds: number },
): Promise<string | null> {
  const reply = await post(
    cfg,
    "/invoice",
    { amount: req.amount, descriptionHash: req.descriptionHash, expirySeconds: req.expirySeconds, network: cfg.network },
    LNBTC_INVOICE_TIMEOUT_MS,
  );
  if (!reply || reply.status !== 200 || typeof reply.body.invoice !== "string") {
    if (reply) console.error("[lnbtc] invoice を発行できません:", reply.status, reply.body.errorReason ?? "");
    return null;
  }
  return reply.body.invoice;
}

export function settlePayment(
  cfg: LnbtcConfig,
  paymentPayload: unknown,
  paymentRequirements: unknown,
): Promise<FacilitatorReply | null> {
  return post(cfg, "/settle", { paymentPayload, paymentRequirements }, LNBTC_SETTLE_TIMEOUT_MS);
}

/** 消費後に提供できなかった 1 件を記録する。 */
export async function recordCredit(
  cfg: LnbtcConfig,
  credit: { consumptionKey: string; resource: string; reason: string },
): Promise<boolean> {
  const reply = await post(cfg, "/credits", credit, LNBTC_SETTLE_TIMEOUT_MS);
  return reply?.status === 200 && reply.body.success === true;
}

/** duplicate_settlement の再送に、未提供分のクレジットを 1 回だけ使う。 */
export async function claimCredit(
  cfg: LnbtcConfig,
  credit: { consumptionKey: string; resource: string; reason: string },
): Promise<boolean> {
  const reply = await post(cfg, "/credits/claim", credit, LNBTC_SETTLE_TIMEOUT_MS);
  return reply?.status === 200 && reply.body.granted === true;
}
