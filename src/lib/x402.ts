// x402 課金コア（Solana USDC exact leg / v1）。osd を参照せず JIN repo 内で自己完結する実装。
// 設計（Solana実装標準 2026-07-08 §1/§3/§4）:
// - accepts は静的自前構築（facilitator の getSupported からは組まない＝OSD regression 回避）。
//   facilitator に決めさせるのは feePayer と verify/settle だけ。
// - feePayer は PayAI /supported の solana エントリ extra.feePayer から動的取得（ローテーションする）。
//   短 TTL キャッシュ + last-known-good fallback。env 固定・ハードコードしない。
// - X-PAYMENT 到達時に facilitator(PayAI) へ verify→settle を引き渡し、X-PAYMENT-RESPONSE(base64)
//   を返す。署名・settle は自前実装しない（PayAI が実行）。
// 参照した公開一次ソース: x402 1.2.0（v1 requirements=maxAmountRequired・verify/settle 本文
//   {x402Version,paymentPayload,paymentRequirements}・settleResponseHeader=base64(JSON)）、
//   @x402/svm exact scheme（extra.feePayer）、PayAI docs（POST /verify・/settle）。

export type PaywallOptions = {
  price: string; // 例 "$0.01"
  description: string;
  resourcePath: string; // 例 "/api/jin/series"
};

const USDC_DECIMALS = 6;

export const NETWORK = process.env.X402_NETWORK ?? "solana";
export const RECIPIENT = process.env.X402_RECIPIENT ?? "";
// facilitator(PayAI)。/supported /verify /settle のベース URL。既定は PayAI 本番（§1 の一次ソース）。
// 空文字 env（設定はされているが値が空）も未設定扱いで既定にフォールバックする（相対URL事故を防ぐ）。
const _facRaw = process.env.X402_FACILITATOR_URL;
export const FACILITATOR_URL =
  _facRaw && _facRaw.trim() ? _facRaw.trim() : "https://facilitator.payai.network";
// 提示バージョン。現行 AA は v1 "solana" クライアント（実測 2026-07-08）。既定 1。
export const X402_VERSION = Number(process.env.X402_VERSION ?? 1);
// 既定は Solana mainnet USDC mint。運用環境で X402_USDC_MINT により上書き可。
export const USDC_MINT =
  process.env.X402_USDC_MINT ?? "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v";

function b64encode(s: string): string {
  return typeof btoa === "function" ? btoa(s) : Buffer.from(s).toString("base64");
}
function b64decode(s: string): string {
  return typeof atob === "function" ? atob(s) : Buffer.from(s, "base64").toString("utf-8");
}

export function priceToAtomic(price: string): string {
  const n = Number(price.replace(/[^0-9.]/g, ""));
  if (!Number.isFinite(n)) return "0";
  return Math.round(n * 10 ** USDC_DECIMALS).toString();
}

export function corsHeaders(): Record<string, string> {
  return {
    "access-control-allow-origin": "*",
    "access-control-allow-methods": "GET, OPTIONS",
    "access-control-allow-headers": "Content-Type, X-PAYMENT",
    // AA クライアントが settle 結果を読めるよう公開する。
    "access-control-expose-headers": "X-PAYMENT-RESPONSE",
  };
}

// --------------------------------------------------------------------------- #
// feePayer 動的取得（/supported。短 TTL + last-known-good fallback。env 固定しない）
// --------------------------------------------------------------------------- #
// feePayer 解決は 4 段 fallback。どの段でも最終的に非空を保証する（症状ごと消す）。
//   1) live: PayAI /supported の solana extra.feePayer（3 分 TTL）
//   2) last-cached: TTL 切れでも直近に取得できた生鮮値
//   3) env: X402_SOLANA_FEE_PAYER
//   4) hardcoded last-known-good（最後の保険。live を殺さない）
// 出典: 本タスク §1/§3 の明示仕様（OSD getSolanaFeePayer と同型。OSD read 不可のため spec から実装）。
const FEEPAYER_TTL_MS = 180_000; // 3 分
export const HARDCODED_FEE_PAYER = "2wKupLR9q6wXYppw8Gr2NvWxKBUqm4PPJKkQfoxHDBg4";
const ENV_FEE_PAYER = (process.env.X402_SOLANA_FEE_PAYER ?? "").trim();
let _feePayerCache: { value: string; ts: number } = { value: "", ts: 0 };

// PayAI /supported のレスポンスから Solana の feePayer を抽出する純関数（単体テスト対象）。
// 期待: network==="solana"（v1・完全一致）の extra.feePayer を優先。無ければ "solana" 前方一致で fallback。
// よくある取り違えを潰す: kinds に潜る / signers 等の別キーを見ない / EVM系(extra無し)で早期returnしない。
export function extractSolanaFeePayer(supported: unknown): string {
  const kinds: unknown[] = Array.isArray(supported)
    ? supported
    : Array.isArray((supported as { kinds?: unknown[] })?.kinds)
      ? (supported as { kinds: unknown[] }).kinds
      : [];
  const feePayerOf = (k: unknown): string => {
    const fp = (k as { extra?: { feePayer?: unknown } })?.extra?.feePayer;
    return typeof fp === "string" ? fp : "";
  };
  // 1) v1 の network==="solana" 完全一致を優先（§1 の期待抽出）。
  for (const k of kinds) {
    if ((k as { network?: unknown })?.network === "solana") {
      const fp = feePayerOf(k);
      if (fp) return fp;
    }
  }
  // 2) fallback: network が "solana" で始まる任意エントリ（"solana:...", "solana-devnet"）。
  for (const k of kinds) {
    const net = (k as { network?: unknown })?.network;
    if (typeof net === "string" && net.startsWith("solana")) {
      const fp = feePayerOf(k);
      if (fp) return fp;
    }
  }
  return "";
}

// 4 段の優先順位を決める純関数（各分岐を単体テストする）: live → last-cached → env → hardcoded。
// どの入力でも最終的に HARDCODED_FEE_PAYER で必ず非空になる。
export function resolveFeePayer(live: string, cached: string, env: string): string {
  return live || cached || env || HARDCODED_FEE_PAYER;
}

// live 取得（PayAI /supported）。失敗時は "" を返す（fallback は getFeePayer 側で処理）。
async function fetchLiveFeePayer(): Promise<string> {
  const url = `${FACILITATOR_URL.replace(/\/$/, "")}/supported`;
  try {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 2500);
    const r = await fetch(url, { signal: ctrl.signal, headers: { accept: "application/json" } });
    clearTimeout(timer);
    if (!r.ok) {
      console.warn(`x402 feePayer: ${url} -> HTTP ${r.status}`);
      return "";
    }
    const fp = extractSolanaFeePayer(await r.json());
    if (!fp) console.warn(`x402 feePayer: solana feePayer not found at ${url}`);
    return fp;
  } catch (e) {
    console.warn(`x402 feePayer: fetch ${url} failed: ${String(e)}`);
    return "";
  }
}

export async function getFeePayer(): Promise<string> {
  const now = Date.now();
  // 1) live: 3 分 TTL 内はキャッシュ済み生鮮値をそのまま使う。
  if (_feePayerCache.value && now - _feePayerCache.ts < FEEPAYER_TTL_MS) return _feePayerCache.value;
  // TTL 切れ / 未取得 → live を叩く。取れたらキャッシュ更新して返す。
  const live = await fetchLiveFeePayer();
  if (live) {
    _feePayerCache = { value: live, ts: now };
    return live;
  }
  // 2) last-cached（TTL 切れでも直近の生鮮値） → 3) env → 4) hardcoded。必ず非空。
  return resolveFeePayer("", _feePayerCache.value, ENV_FEE_PAYER);
}

// --------------------------------------------------------------------------- #
// accepts（静的 v1 leg。feePayer だけ動的）
// --------------------------------------------------------------------------- #
export function paymentRequirements(opts: PaywallOptions, feePayer: string) {
  return {
    scheme: "exact",
    network: NETWORK,
    maxAmountRequired: priceToAtomic(opts.price), // v1 は maxAmountRequired（atomic 整数文字列）
    resource: opts.resourcePath,
    description: opts.description,
    mimeType: "application/json",
    payTo: RECIPIENT,
    asset: USDC_MINT,
    maxTimeoutSeconds: 60,
    // 実測リファレンス（2026-07-08）の exact SVM 形: extra は { resource, feePayer }。
    extra: { resource: opts.resourcePath, feePayer },
  };
}

export async function buildAccepts(opts: PaywallOptions) {
  return [paymentRequirements(opts, await getFeePayer())];
}

export async function challenge402(opts: PaywallOptions): Promise<Response> {
  const body = {
    x402Version: X402_VERSION,
    error: "payment required",
    accepts: await buildAccepts(opts),
  };
  return Response.json(body, { status: 402, headers: corsHeaders() });
}

// --------------------------------------------------------------------------- #
// verify → settle（facilitator/PayAI 引き渡し。署名・settle は自前化しない）
// --------------------------------------------------------------------------- #
async function facilitatorPost(path: string, payload: unknown): Promise<Record<string, unknown> | null> {
  try {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 8000);
    const r = await fetch(`${FACILITATOR_URL.replace(/\/$/, "")}${path}`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
      signal: ctrl.signal,
    });
    clearTimeout(timer);
    if (!r.ok) return null;
    return (await r.json()) as Record<string, unknown>;
  } catch {
    return null;
  }
}

export type SettleOutcome = { pass: boolean; responseHeader?: string };

// X-PAYMENT 到達時: PaymentPayload を facilitator に渡して verify→settle し、
// X-PAYMENT-RESPONSE 用の base64 ヘッダ値（= settleResponseHeader）を返す。
export async function verifyThenSettle(
  xpayment: string,
  opts: PaywallOptions,
): Promise<SettleOutcome> {
  let paymentPayload: unknown;
  try {
    paymentPayload = JSON.parse(b64decode(xpayment));
  } catch {
    return { pass: false };
  }
  const requirements = paymentRequirements(opts, await getFeePayer());
  const body = { x402Version: X402_VERSION, paymentPayload, paymentRequirements: requirements };

  const verifyRes = await facilitatorPost("/verify", body);
  const valid = Boolean(verifyRes && (verifyRes.isValid ?? verifyRes.valid));
  if (!valid) return { pass: false };

  const settleRes = await facilitatorPost("/settle", body);
  if (!settleRes) return { pass: false };
  // settleResponseHeader(response) = base64(JSON.stringify(response))（x402 1.2.0）。
  const responseHeader = b64encode(JSON.stringify(settleRes));
  return { pass: settleRes.success === true, responseHeader };
}
