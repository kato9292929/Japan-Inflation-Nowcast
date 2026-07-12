// x402 native server 配線（OSD PR #16 と同型）。self-build を廃し SDK に委譲する。
// PayAI facilitator が getSupported() で v2 kind + live feePayer を供給する
// （＝自前 feePayer fallback は不要。stale-feePayer 問題は native では消える）。
import { createFacilitatorConfig as createPayAIFacilitatorConfig } from "@payai/facilitator";
import { HTTPFacilitatorClient, x402ResourceServer } from "@x402/core/server";
import { registerExactSvmScheme } from "@x402/svm/exact/server";

// Solana は PayAI facilitator。API キーは任意（無くても free tier）。
const payaiFacilitatorClient = new HTTPFacilitatorClient(
  createPayAIFacilitatorConfig(
    process.env.PAYAI_API_KEY_ID,
    process.env.PAYAI_API_KEY_SECRET,
  ),
);

// JIN は Solana のみ（Base leg は出さない）。
export const x402Server = new x402ResourceServer([payaiFacilitatorClient]);

// solana:* (CAIP-2 / v2) を登録。bare "solana" v1 は手動 register しない。
registerExactSvmScheme(x402Server);
