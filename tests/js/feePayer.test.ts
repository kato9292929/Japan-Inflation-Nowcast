// feePayer 抽出の単体テスト（実物 fixture = PayAI /supported の本番 curl 実測）。
// 実行: npx tsx --test tests/js/feePayer.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { extractSolanaFeePayer } from "../../src/lib/x402";

const here = dirname(fileURLToPath(import.meta.url));
const fixture = JSON.parse(readFileSync(join(here, "payai-supported.json"), "utf-8"));

const EXPECTED = "2wKupLR9q6wXYppw8Gr2NvWxKBUqm4PPJKkQfoxHDBg4";

test("実測 fixture から v1 solana の feePayer を抽出できる", () => {
  assert.equal(extractSolanaFeePayer(fixture), EXPECTED);
});

test("kinds 無し / 空 は空文字", () => {
  assert.equal(extractSolanaFeePayer({}), "");
  assert.equal(extractSolanaFeePayer({ kinds: [] }), "");
  assert.equal(extractSolanaFeePayer(null), "");
});

test("EVM系(extra無し)を先に踏んでも早期returnせず solana を拾う", () => {
  const data = {
    kinds: [
      { x402Version: 1, scheme: "exact", network: "base" },
      { x402Version: 1, scheme: "exact", network: "solana", extra: { feePayer: "FP123" } },
    ],
  };
  assert.equal(extractSolanaFeePayer(data), "FP123");
});

test("solana:... (v2) が配列先頭でも v1 の 'solana' 完全一致を優先", () => {
  const data = {
    kinds: [
      { network: "solana:5eykt", extra: { feePayer: "V2FP" } },
      { network: "solana", extra: { feePayer: "V1FP" } },
    ],
  };
  assert.equal(extractSolanaFeePayer(data), "V1FP");
});

test("v1 'solana' が無ければ solana 前方一致で fallback", () => {
  const data = { kinds: [{ network: "solana:5eykt", extra: { feePayer: "V2FP" } }] };
  assert.equal(extractSolanaFeePayer(data), "V2FP");
});
