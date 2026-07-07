// x402 課金コア（Solana USDC leg）。osd を参照せず JIN repo 内で自己完結する実装。
// 観測データ配信のための最小ゲート: X-PAYMENT が無ければ 402 challenge、
// あれば facilitator で検証して通す。facilitator 未設定なら検証不能として閉じる（402）。

export type PaywallOptions = {
  price: string; // 例 "$0.01"
  description: string;
  resourcePath: string; // 例 "/api/jin/series"
};

const USDC_DECIMALS = 6;

export const NETWORK = process.env.X402_NETWORK ?? "solana";
export const RECIPIENT = process.env.X402_RECIPIENT ?? "";
export const FACILITATOR_URL = process.env.X402_FACILITATOR_URL ?? "";
// x402 プロトコルの提示バージョン。AA/facilitator の受理形に合わせて運用者が設定する。
// 既定 2（AA parser が v2 accepts 形式を要求するため）。1 に戻す場合は X402_VERSION=1。
// discovery と 402 challenge の両方がこの単一ソースを使い、バージョン差を作らない。
export const X402_VERSION = Number(process.env.X402_VERSION ?? 2);
// 既定は Solana mainnet USDC mint。運用環境で X402_USDC_MINT により上書き可。
export const USDC_MINT =
  process.env.X402_USDC_MINT ?? "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v";

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
  };
}

export function paymentRequirements(opts: PaywallOptions) {
  return {
    scheme: "exact",
    network: NETWORK,
    maxAmountRequired: priceToAtomic(opts.price),
    resource: opts.resourcePath,
    description: opts.description,
    mimeType: "application/json",
    payTo: RECIPIENT,
    asset: USDC_MINT,
    maxTimeoutSeconds: 60,
    extra: { decimals: USDC_DECIMALS, priceUsd: opts.price },
  };
}

export function challenge402(opts: PaywallOptions): Response {
  const body = {
    x402Version: X402_VERSION,
    error: "payment required",
    accepts: [paymentRequirements(opts)],
  };
  return Response.json(body, { status: 402, headers: corsHeaders() });
}

export async function verifyPayment(req: Request, opts: PaywallOptions): Promise<boolean> {
  const payment = req.headers.get("x-payment");
  if (!payment) return false;
  if (!FACILITATOR_URL) return false; // 検証不能 → 安全側で閉じる
  try {
    const r = await fetch(`${FACILITATOR_URL.replace(/\/$/, "")}/verify`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ payment, requirements: paymentRequirements(opts) }),
    });
    if (!r.ok) return false;
    const d = (await r.json()) as { valid?: boolean; isValid?: boolean };
    return Boolean(d.valid ?? d.isValid ?? false);
  } catch {
    return false;
  }
}
