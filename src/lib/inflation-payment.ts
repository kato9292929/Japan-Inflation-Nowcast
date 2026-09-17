export const INFLATION_PRICE = "$0.01";

// ユーザーが明示的にtrueを設定した場合だけ課金する。
export function inflationPaymentsEnabled() {
  return process.env.INFLATION_X402_ENABLED === "true";
}
