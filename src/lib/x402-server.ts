// x402 native server 配線（OSD PR #16 と同型）。self-build を廃し SDK に委譲する。
// facilitator（既定は PayAI）が getSupported() で v2 kind + live feePayer を供給する
// （＝自前 feePayer fallback は不要。stale-feePayer 問題は native では消える）。
import { createFacilitatorConfig as createPayAIFacilitatorConfig } from "@payai/facilitator";
import { HTTPFacilitatorClient, x402ResourceServer } from "@x402/core/server";
import { registerExactSvmScheme } from "@x402/svm/exact/server";

// Solana の facilitator。SOLANA_FACILITATOR_URL が設定されていればそれを使う
// （kato9292929/x402-facilitator：Phantom の Lighthouse 確認命令も受け付ける）。
// 未設定なら PayAI。API キーは任意（無くても free tier）。
const solanaFacilitatorUrl = process.env.SOLANA_FACILITATOR_URL?.trim();
const facilitatorClient = solanaFacilitatorUrl
  ? new HTTPFacilitatorClient({ url: solanaFacilitatorUrl })
  : new HTTPFacilitatorClient(
      createPayAIFacilitatorConfig(
        process.env.PAYAI_API_KEY_ID,
        process.env.PAYAI_API_KEY_SECRET,
      ),
    );

// JIN は Solana のみ（Base leg は出さない）。
export const x402Server = new x402ResourceServer([facilitatorClient]);

// solana:* (CAIP-2 / v2) を登録。bare "solana" v1 は手動 register しない。
registerExactSvmScheme(x402Server);
