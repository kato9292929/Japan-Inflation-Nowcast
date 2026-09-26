// x402 exact/lnbtc リクエストバインディングの既知応答テスト。
// 期待値は仕様 specs/schemes/exact/scheme_exact_lnbtc.md の
// "Request Binding Test Vectors" をそのまま写したもの（2026-09-26 取得）。
// 実ノード・実支払い・ネットワークは一切使わない。

import { describe, expect, it } from "vitest";
import { JcsError, canonicalize } from "@/lib/jcs";
import {
  DEFAULT_SKEW_SECONDS,
  LNBTC_NETWORKS,
  LnbtcError,
  absentValueHash,
  assertMillisatoshiAmount,
  canonicalDescription,
  checkInvoiceTiming,
  consumptionKey,
  httpBinding,
  mcpBinding,
  presentMetadataValueHash,
  replayRetainUntil,
  requestHash,
  verifyPreimage,
} from "@/lib/lnbtc";

// --- 仕様のテストベクタ（HTTP） ------------------------------------------- //
const HTTP_A_DESCRIPTION =
  '{"bodyHash":"e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",' +
  '"domain":"x402:exact:lnbtc:bolt11:http:1","headers":[],"method":"GET",' +
  '"url":"https://api.example.com/article/A"}';
const HTTP_A_HASH = "0d6623f775e025501fa7f0a30b54da25aad62b6ccfe35c85da38016711e6c018";
const HTTP_B_HASH = "4a99860f75eed1ea8178a5db488e044173bc570c8a6210f2c8590cdf8622d509";

const httpArticle = (article: string) =>
  httpBinding({
    method: "GET",
    url: `https://api.example.com/article/${article}`,
    boundHeaders: [],
  });

describe("http:1 プロファイル", () => {
  it("正規化文字列が仕様の1行と完全一致する", () => {
    expect(canonicalDescription(httpArticle("A"))).toBe(HTTP_A_DESCRIPTION);
  });

  it("requestHash が仕様のダイジェストと一致する", () => {
    expect(requestHash(httpArticle("A"))).toBe(HTTP_A_HASH);
  });

  it("URL だけを変えると仕様どおり別のダイジェストになる", () => {
    expect(requestHash(httpArticle("B"))).toBe(HTTP_B_HASH);
    expect(requestHash(httpArticle("B"))).not.toBe(HTTP_A_HASH);
  });

  it("method・本文を変えるとダイジェストが変わる（付け替えを弾く根拠）", () => {
    const post = httpBinding({
      method: "POST",
      url: "https://api.example.com/article/A",
      boundHeaders: [],
    });
    const body = httpBinding({
      method: "GET",
      url: "https://api.example.com/article/A",
      body: Buffer.of(0x78),
      boundHeaders: [],
    });
    expect(requestHash(post)).not.toBe(HTTP_A_HASH);
    expect(requestHash(body)).not.toBe(HTTP_A_HASH);
  });

  it("bound header の一覧を変えるとダイジェストが変わる", () => {
    const withHeader = httpBinding({
      method: "GET",
      url: "https://api.example.com/article/A",
      boundHeaders: ["accept"],
    });
    expect(requestHash(withHeader)).not.toBe(HTTP_A_HASH);
  });

  it("不在ヘッダと空文字列ヘッダを区別する", () => {
    const absent = httpBinding({
      method: "GET",
      url: "https://api.example.com/article/A",
      boundHeaders: ["accept"],
    });
    const empty = httpBinding({
      method: "GET",
      url: "https://api.example.com/article/A",
      boundHeaders: ["accept"],
      headers: { accept: "" },
    });
    expect(requestHash(absent)).not.toBe(requestHash(empty));
  });

  it("不在ダイジェストは SHA-256(0x00)（仕様の metadata 不在値と同じ）", () => {
    expect(absentValueHash()).toBe(
      "6e340b9cffb37a989ca544e6bb780a2c78901d3fb33738768511a30617afa01d",
    );
  });

  it("bound header 名の規則違反を拒否する", () => {
    const base = { method: "GET", url: "https://api.example.com/article/A" };
    expect(() => httpBinding({ ...base, boundHeaders: ["Accept"] })).toThrow(LnbtcError);
    expect(() => httpBinding({ ...base, boundHeaders: ["range", "accept"] })).toThrow(LnbtcError);
    expect(() => httpBinding({ ...base, boundHeaders: ["accept", "accept"] })).toThrow(LnbtcError);
    expect(() => httpBinding({ ...base, boundHeaders: ["payment-signature"] })).toThrow(LnbtcError);
  });

  it("fragment・userinfo・相対 URL を拒否する", () => {
    const base = { method: "GET", boundHeaders: [] as string[] };
    expect(() => httpBinding({ ...base, url: "https://api.example.com/a#x" })).toThrow(LnbtcError);
    expect(() => httpBinding({ ...base, url: "https://u:p@api.example.com/a" })).toThrow(LnbtcError);
    expect(() => httpBinding({ ...base, url: "/article/A" })).toThrow(LnbtcError);
  });
});

// --- 仕様のテストベクタ（MCP） -------------------------------------------- //
const MCP_A_DESCRIPTION =
  '{"arguments":{"article":"A"},"domain":"x402:exact:lnbtc:bolt11:mcp:1","metadata":[],' +
  '"method":"tools/call","name":"get_article","server":"https://api.example.com/mcp"}';
const MCP_A_HASH = "03941bfedc6af8a09b2f459fe83470284a76a8c75801caa9e1487a9276a693f4";

const mcpCall = (over: Partial<Parameters<typeof mcpBinding>[0]> = {}) =>
  mcpBinding({
    server: "https://api.example.com/mcp",
    name: "get_article",
    arguments: { article: "A" },
    boundMetadata: [],
    ...over,
  });

describe("mcp:1 プロファイル", () => {
  it("正規化文字列が仕様の1行と完全一致する", () => {
    expect(canonicalDescription(mcpCall())).toBe(MCP_A_DESCRIPTION);
  });

  it("requestHash が仕様のダイジェストと一致する", () => {
    expect(requestHash(mcpCall())).toBe(MCP_A_HASH);
  });

  it.each([
    ["arguments.article を B に", { arguments: { article: "B" } },
      "b3e425970d64cd4f08fc4d57a11b76da59ce6a5760d92687398c91f063120678"],
    ["name を delete_article に", { name: "delete_article" },
      "3a52bbf19dda8b5765a27246b12e805770298273b48526956c421f02fe043455"],
    ["server を other.example.com に", { server: "https://other.example.com/mcp" },
      "96903c29186c6aabc95e48abafd8ce3ad32b4060f5d5bf22cf75f3fbfe816e45"],
  ])("%s 変えると仕様どおりのダイジェストになる", (_label, over, expected) => {
    expect(requestHash(mcpCall(over))).toBe(expected);
  });

  it("metadata の不在と present null を仕様どおり区別する", () => {
    expect(absentValueHash()).toBe(
      "6e340b9cffb37a989ca544e6bb780a2c78901d3fb33738768511a30617afa01d",
    );
    expect(presentMetadataValueHash(null)).toBe(
      "c58dcb77cee9027d1f4b3207bd876d232e61f79ee9f9dbd4e6d834778da78b16",
    );
  });

  it("JSON-RPC id・progressToken・payment metadata はハッシュ入力ではない", () => {
    const withIgnored = mcpCall({
      meta: { progressToken: "t-1", "x402/payment": { preimage: "00".repeat(32) } },
      boundMetadata: [],
    });
    expect(requestHash(withIgnored)).toBe(MCP_A_HASH);
  });

  it("arguments のメンバ順・空白差ではダイジェストが変わらない", () => {
    const reparsed = JSON.parse('{ "article" : "A" }');
    expect(requestHash(mcpCall({ arguments: reparsed }))).toBe(MCP_A_HASH);
  });

  it("arguments 省略と {} を同一に扱う", () => {
    expect(requestHash(mcpCall({ arguments: undefined }))).toBe(
      requestHash(mcpCall({ arguments: {} })),
    );
  });

  it("null・非オブジェクトの arguments と _meta を拒否する", () => {
    expect(() => mcpCall({ arguments: null })).toThrow(LnbtcError);
    expect(() => mcpCall({ arguments: [1] })).toThrow(LnbtcError);
    expect(() => mcpCall({ meta: 1 })).toThrow(LnbtcError);
  });

  it("x402/payment と progressToken を bound metadata にできない", () => {
    expect(() => mcpCall({ boundMetadata: ["x402/payment"] })).toThrow(LnbtcError);
    expect(() => mcpCall({ boundMetadata: ["progressToken"] })).toThrow(LnbtcError);
  });

  it("HTTP と MCP のドメインタグが違うので同じ素材でも衝突しない", () => {
    expect(requestHash(mcpCall())).not.toBe(HTTP_A_HASH);
  });
});

// --- preimage 検証 -------------------------------------------------------- //
describe("支払い証明", () => {
  // SHA-256(0x00 × 32) は既知値。受信ノードに接続せずローカル検証できる。
  const preimage = "00".repeat(32);
  const paymentHash = "66687aadf862bd776c8fc18b8e9f8e20089714856ee233b3902a591d0d5f2925";

  it("一致する preimage を受け入れる", () => {
    expect(verifyPreimage(preimage, paymentHash)).toBe(true);
  });

  it("不一致を拒否する", () => {
    expect(verifyPreimage("01".repeat(32), paymentHash)).toBe(false);
  });

  it("64 桁小文字 16 進以外を拒否する", () => {
    expect(() => verifyPreimage("00".repeat(31), paymentHash)).toThrow(LnbtcError);
    expect(() => verifyPreimage("ab".repeat(32).toUpperCase(), paymentHash)).toThrow(LnbtcError);
    expect(() => verifyPreimage(preimage, paymentHash.toUpperCase())).toThrow(LnbtcError);
    expect(() => verifyPreimage("zz".repeat(32), paymentHash)).toThrow(LnbtcError);
  });
});

// --- 消費キーと期限 ------------------------------------------------------- //
describe("リプレイ防止", () => {
  const hash = "a923c2c0e4fe77061ff1cb882171f6fdf926719bb7f5ffe2e05458438c52825e";

  it("消費キーは network:payment_hash（payment_hash 単体ではない）", () => {
    expect(consumptionKey(LNBTC_NETWORKS.mainnet.network, hash)).toBe(
      `${LNBTC_NETWORKS.mainnet.network}:${hash}`,
    );
  });

  it("同じ payment_hash でも testnet と mainnet で別キーになる", () => {
    expect(consumptionKey(LNBTC_NETWORKS.testnet.network, hash)).not.toBe(
      consumptionKey(LNBTC_NETWORKS.mainnet.network, hash),
    );
  });

  it("未対応ネットワークを拒否する", () => {
    expect(() => consumptionKey("lnbtc:deadbeef", hash)).toThrow(LnbtcError);
  });

  it("保持期限は invoice_end + skew の 1 時間後", () => {
    expect(replayRetainUntil({ invoiceCreatedAt: 1_700_000_000, invoiceExpirySeconds: 300 })).toBe(
      1_700_000_000 + 300 + DEFAULT_SKEW_SECONDS + 3600,
    );
  });
});

describe("invoice の時刻判定", () => {
  const base = { invoiceCreatedAt: 1_700_000_000, invoiceExpirySeconds: 300 };
  const end = base.invoiceCreatedAt + base.invoiceExpirySeconds;

  it("期限後でも skew の境界ちょうどまでは通す", () => {
    expect(checkInvoiceTiming({ ...base, settlementTime: end + DEFAULT_SKEW_SECONDS })).toEqual({
      ok: true,
    });
  });

  it("境界を 1 秒超えたら拒否する", () => {
    expect(checkInvoiceTiming({ ...base, settlementTime: end + DEFAULT_SKEW_SECONDS + 1 })).toEqual({
      ok: false,
      reason: "invoice_expired",
    });
  });

  it("作成時刻が settlement + skew ちょうどは通し、1 秒超は拒否する", () => {
    const settlementTime = 1_700_000_000;
    expect(
      checkInvoiceTiming({
        ...base,
        invoiceCreatedAt: settlementTime + DEFAULT_SKEW_SECONDS,
        settlementTime,
      }),
    ).toEqual({ ok: true });
    expect(
      checkInvoiceTiming({
        ...base,
        invoiceCreatedAt: settlementTime + DEFAULT_SKEW_SECONDS + 1,
        settlementTime,
      }),
    ).toEqual({ ok: false, reason: "invoice_created_in_future" });
  });
});

// --- 金額と JCS の拒否条件 ------------------------------------------------ //
describe("金額", () => {
  it("ミリサトシの正の整数文字列だけを受け入れる", () => {
    expect(assertMillisatoshiAmount("21000")).toBe("21000");
    for (const bad of ["0", "-1", "21.5", "2e4", "21 sat", "21,000", "+21", ""]) {
      expect(() => assertMillisatoshiAmount(bad)).toThrow(LnbtcError);
    }
  });
});

describe("JCS の拒否条件", () => {
  it("非有限数を拒否する", () => {
    expect(() => canonicalize({ a: Number.NaN })).toThrow(JcsError);
    expect(() => canonicalize({ a: Number.POSITIVE_INFINITY })).toThrow(JcsError);
  });

  it("孤立サロゲートを拒否する", () => {
    expect(() => canonicalize({ a: "\ud800" })).toThrow(JcsError);
  });

  it("メンバを UTF-16 コードユニット順に並べる", () => {
    expect(canonicalize({ b: 1, a: 2, A: 3 })).toBe('{"A":3,"a":2,"b":1}');
  });
});
