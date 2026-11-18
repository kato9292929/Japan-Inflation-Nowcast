// x402 exact/lnbtc（Bitcoin Lightning）の設定。ファシリテーターは kato9292929/lnbtc-facilitator
// （https://lnbtc.x402jp.com）。invoice の発行と支払い証明の検証・消費はファシリテーターが行い、
// JIN はリクエストハッシュの計算と 402 への選択肢の追加、/settle の呼び出しだけを持つ。
//
// LNBTC_ENABLED=true と鍵・payTo が揃ったときだけ有効。揃わなければ lnbtc は 402 に出さず、
// Solana だけで動く（既存の挙動のまま）。

import { LNBTC_NETWORKS, type LnbtcNetwork } from "./lnbtc";

/** msat 建ての価格。lnbtc-facilitator の facilitator/pricing.py の PRICES_MSAT と同じ値。 */
export const LNBTC_PRICES_MSAT: Readonly<Record<string, string>> = {
  "/api/jin/series": "12000",
  "/api/jin/movers": "24000",
};

/** invoice の有効期間（= maxTimeoutSeconds）。ファシリテーターの上限は 3600 秒。 */
export const LNBTC_MAX_TIMEOUT_SECONDS = 300;
/** 402 を出すときの invoice 発行の待ち時間。超えたら lnbtc を外して Solana だけで返す。 */
export const LNBTC_INVOICE_TIMEOUT_MS = 1000;
/** /settle・/credits の待ち時間。 */
export const LNBTC_SETTLE_TIMEOUT_MS = 5000;

export type LnbtcConfig = {
  facilitatorUrl: string;
  keyId: string;
  secret: string;
  payTo: string;
  network: LnbtcNetwork;
};

const PAY_TO_PATTERN = /^0[23][0-9a-f]{64}$/;
const KEY_ID_PATTERN = /^[A-Za-z0-9._-]{1,64}$/;

/** 有効なら設定を返す。無効・不完全なら null（理由はログにだけ出す。秘密は出さない）。 */
export function lnbtcConfig(): LnbtcConfig | null {
  if (process.env.LNBTC_ENABLED !== "true") return null;
  const facilitatorUrl = (process.env.LNBTC_FACILITATOR_URL ?? "https://lnbtc.x402jp.com").replace(/\/$/, "");
  const keyId = process.env.LNBTC_HMAC_KEY_ID ?? "";
  const secret = process.env.LNBTC_HMAC_SECRET ?? "";
  const payTo = process.env.LNBTC_PAY_TO ?? "";
  const networkName = process.env.LNBTC_NETWORK ?? "mainnet";
  const problems: string[] = [];
  if (!facilitatorUrl.startsWith("https://")) problems.push("LNBTC_FACILITATOR_URL は https");
  if (!KEY_ID_PATTERN.test(keyId)) problems.push("LNBTC_HMAC_KEY_ID");
  if (secret.length < 32) problems.push("LNBTC_HMAC_SECRET（32 文字以上）");
  if (!PAY_TO_PATTERN.test(payTo)) problems.push("LNBTC_PAY_TO（66 桁・小文字 16 進）");
  if (networkName !== "mainnet" && networkName !== "testnet") problems.push("LNBTC_NETWORK（mainnet か testnet）");
  if (problems.length > 0) {
    console.error("[lnbtc] 設定が不完全なので lnbtc を出しません:", problems.join(", "));
    return null;
  }
  return {
    facilitatorUrl,
    keyId,
    secret,
    payTo,
    network: LNBTC_NETWORKS[networkName as "mainnet" | "testnet"].network,
  };
}
