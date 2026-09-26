// x402 `exact` / `lnbtc`（Bitcoin Lightning）のリクエストバインディングと支払い証明。
// 出典: x402 仕様 specs/schemes/exact/scheme_exact_lnbtc.md（main、2026-09-26 取得）。
//
// ここに入れるのは実ノードも実支払いも不要な純ロジックだけ。invoice の発行・支払い・
// decode は含まない。仕様上、リクエストハッシュの再計算は resource server の責務
// （「paid retry では実行されるリクエストから再計算し、accepted.extra や invoice から
// 取ってはならない」）なので、TypeScript 側に置く必要がある。
//
// リプレイストアの実体（原子的・再起動耐性）は含まない。消費キーと期限判定だけを提供する。

import { createHash } from "node:crypto";
import { canonicalBytes, canonicalize } from "./jcs";

export class LnbtcError extends Error {}

// CAIP-2 network は BIP-122 に従い genesis hash 先頭 32 文字。BOLT11 通貨も対応させる。
export const LNBTC_NETWORKS = {
  mainnet: { network: "lnbtc:000000000019d6689c085ae165831e93", bolt11Currency: "bc" },
  testnet: { network: "lnbtc:000000000933ea01ad0ee984209779ba", bolt11Currency: "tb" },
} as const;

export type LnbtcNetwork = (typeof LNBTC_NETWORKS)[keyof typeof LNBTC_NETWORKS]["network"];

export const SCHEME = "exact";
export const ASSET = "BTC";
export const ASSET_TRANSFER_METHOD = "bolt11";
export const PAYMENT_FLOW = "upfront";
/** 仕様の既定クロックスキュー。invoice 作成時刻の上限と支払後猶予の両方に使う同一の値。 */
export const DEFAULT_SKEW_SECONDS = 60;

const DOMAIN_PREFIX = "x402:exact:lnbtc:bolt11:";
const HEX32 = /^[0-9a-f]{64}$/;

const sha256 = (input: Buffer) => createHash("sha256").update(input).digest();
const hex = (input: Buffer) => input.toString("hex");

/** 存在するヘッダ値のダイジェスト: SHA-256(0x01 || ASCII(value))。 */
export function presentHeaderValueHash(value: string): string {
  if (!/^[\x00-\x7f]*$/.test(value)) throw new LnbtcError("ヘッダ値が ASCII ではありません");
  return hex(sha256(Buffer.concat([Buffer.of(0x01), Buffer.from(value, "ascii")])));
}

/** 存在する metadata 値のダイジェスト: SHA-256(0x01 || UTF8(JCS(value)))。null も「存在」。 */
export function presentMetadataValueHash(value: unknown): string {
  return hex(sha256(Buffer.concat([Buffer.of(0x01), canonicalBytes(value)])));
}

/** 不在のダイジェスト: SHA-256(0x00)。空文字列の値と区別するために存在する。 */
export function absentValueHash(): string {
  return hex(sha256(Buffer.of(0x00)));
}

/** 本文のダイジェスト。本文が無い場合は空バイト列の SHA-256。 */
export function bodyHash(body?: Buffer | null): string {
  return hex(sha256(body ?? Buffer.alloc(0)));
}

function assertBoundHeaderNames(names: readonly string[]): void {
  for (const name of names) {
    if (!/^[!#$%&'*+\-.^_`|~0-9a-z]+$/.test(name)) {
      throw new LnbtcError(`bound header 名が小文字トークンではありません: ${name}`);
    }
  }
  if (names.includes("payment-signature")) {
    throw new LnbtcError("payment-signature は bound header に含められません");
  }
  for (let i = 1; i < names.length; i += 1) {
    if (names[i - 1] === names[i]) throw new LnbtcError(`bound header 名が重複しています: ${names[i]}`);
    if (names[i - 1] > names[i]) throw new LnbtcError("bound header 名が ASCII 昇順ではありません");
  }
}

function assertBindingUrl(url: string, label: string): void {
  if (!/^[\x00-\x7f]*$/.test(url)) throw new LnbtcError(`${label} が ASCII ではありません`);
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    throw new LnbtcError(`${label} が絶対 URL ではありません`);
  }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    throw new LnbtcError(`${label} が http/https ではありません`);
  }
  if (url.includes("#")) throw new LnbtcError(`${label} に fragment を含められません`);
  if (parsed.username || parsed.password) throw new LnbtcError(`${label} に userinfo を含められません`);
}

export type HttpBindingInput = {
  /** RFC 9421 @method。大文字小文字はそのまま保つ。 */
  method: string;
  /** RFC 9421 @target-uri。クエリを含む絶対 URL。fragment / userinfo は不可。 */
  url: string;
  /** 転送デコード後・コンテンツデコード前の本文バイト列。JSON を再直列化してはならない。 */
  body?: Buffer | null;
  /** サーバ設定の bound header 名（小文字・ASCII 昇順・重複なし）。クライアントのエコーは使わない。 */
  boundHeaders: readonly string[];
  /** 実リクエストのヘッダ。未設定は「不在」として 0x00 ダイジェストになる。 */
  headers?: Readonly<Record<string, string | undefined>>;
};

/** http:1 プロファイルのバインディングオブジェクトを実リクエストから組み立てる。 */
export function httpBinding(input: HttpBindingInput): Record<string, unknown> {
  if (!input.method) throw new LnbtcError("method が空です");
  assertBindingUrl(input.url, "url");
  assertBoundHeaderNames(input.boundHeaders);
  return {
    domain: `${DOMAIN_PREFIX}http:1`,
    method: input.method,
    url: input.url,
    bodyHash: bodyHash(input.body),
    headers: input.boundHeaders.map((name) => {
      const value = input.headers?.[name];
      return {
        name,
        valueHash: value === undefined ? absentValueHash() : presentHeaderValueHash(value),
      };
    }),
  };
}

export type McpBindingInput = {
  /** サーバ設定側の MCP エンドポイント URI。クライアントのエコーは使わない。 */
  server: string;
  /** params.name。非空・正規化しない。 */
  name: string;
  /** params.arguments。省略時は {}。null・非オブジェクトは拒否。 */
  arguments?: unknown;
  /** サーバ設定の bound metadata 名（JCS 順・重複なし）。 */
  boundMetadata: readonly string[];
  /** 実 params._meta。不在は空オブジェクト扱い。非オブジェクトは拒否。 */
  meta?: unknown;
};

/** mcp:1 プロファイル（tools/call 専用）のバインディングオブジェクトを組み立てる。 */
export function mcpBinding(input: McpBindingInput): Record<string, unknown> {
  assertBindingUrl(input.server, "server");
  if (!input.name) throw new LnbtcError("tool 名が空です");

  const args = input.arguments === undefined ? {} : input.arguments;
  if (args === null || typeof args !== "object" || Array.isArray(args)) {
    throw new LnbtcError("arguments はオブジェクトでなければなりません");
  }

  const meta = input.meta === undefined ? {} : input.meta;
  if (meta === null || typeof meta !== "object" || Array.isArray(meta)) {
    throw new LnbtcError("_meta はオブジェクトでなければなりません");
  }
  const metaRecord = meta as Record<string, unknown>;

  const names = input.boundMetadata;
  for (const name of names) {
    if (!name) throw new LnbtcError("bound metadata 名が空です");
    if (name === "x402/payment" || name === "progressToken") {
      throw new LnbtcError(`${name} は bound metadata に含められません`);
    }
  }
  for (let i = 1; i < names.length; i += 1) {
    if (names[i - 1] === names[i]) throw new LnbtcError(`bound metadata 名が重複しています: ${names[i]}`);
    if (names[i - 1] > names[i]) throw new LnbtcError("bound metadata 名が JCS 順ではありません");
  }

  return {
    domain: `${DOMAIN_PREFIX}mcp:1`,
    server: input.server,
    method: "tools/call",
    name: input.name,
    arguments: args,
    metadata: names.map((name) => ({
      name,
      valueHash: Object.hasOwn(metaRecord, name)
        ? presentMetadataValueHash(metaRecord[name])
        : absentValueHash(),
    })),
  };
}

/** description bytes = UTF8(JCS(binding))。invoice の description hash の入力そのもの。 */
export function descriptionBytes(binding: Record<string, unknown>): Buffer {
  return canonicalBytes(binding);
}

/** requestHash = SHA-256(descriptionBytes)。64 桁小文字 16 進。 */
export function requestHash(binding: Record<string, unknown>): string {
  return hex(sha256(descriptionBytes(binding)));
}

/** デバッグ・テスト用に正規化文字列をそのまま見る。 */
export function canonicalDescription(binding: Record<string, unknown>): string {
  return canonicalize(binding);
}

/** SHA-256(preimage) == payment_hash をローカル検証する。受信ノードへの接続は不要。 */
export function verifyPreimage(preimage: string, paymentHash: string): boolean {
  if (!HEX32.test(preimage)) throw new LnbtcError("preimage は 64 桁小文字 16 進でなければなりません");
  if (!HEX32.test(paymentHash)) throw new LnbtcError("payment_hash は 64 桁小文字 16 進でなければなりません");
  return hex(sha256(Buffer.from(preimage, "hex"))) === paymentHash;
}

/**
 * リプレイストアの消費キー。仕様は network を含めることを要求する
 * （同じ payment_hash でもネットワークが違えば別キー）。payment_hash 単体では
 * testnet と mainnet が衝突する。
 */
export function consumptionKey(network: string, paymentHash: string): string {
  if (!Object.values(LNBTC_NETWORKS).some((n) => n.network === network)) {
    throw new LnbtcError(`未対応のネットワーク: ${network}`);
  }
  if (!HEX32.test(paymentHash)) throw new LnbtcError("payment_hash は 64 桁小文字 16 進でなければなりません");
  return `${network}:${paymentHash}`;
}

export type ExpiryCheck = {
  /** invoice の作成時刻（Unix 秒）。 */
  invoiceCreatedAt: number;
  /** invoice の expiry 秒。maxTimeoutSeconds と一致していなければならない。 */
  invoiceExpirySeconds: number;
  /** /settle 時の検証時刻（Unix 秒）。 */
  settlementTime: number;
  skewSeconds?: number;
};

/**
 * 仕様の paid-but-expired ポリシー。invoice_end = 作成時刻 + expiry とし、
 * settlement_time <= invoice_end + skew の間は BOLT11 期限後でも通す（境界は有効）。
 * あわせて作成時刻が settlement_time + skew を超えないことも要求する。
 */
export function checkInvoiceTiming({
  invoiceCreatedAt,
  invoiceExpirySeconds,
  settlementTime,
  skewSeconds = DEFAULT_SKEW_SECONDS,
}: ExpiryCheck): { ok: true } | { ok: false; reason: "invoice_expired" | "invoice_created_in_future" } {
  if (skewSeconds < 0) throw new LnbtcError("skew は非負でなければなりません");
  if (!Number.isInteger(invoiceExpirySeconds) || invoiceExpirySeconds <= 0) {
    throw new LnbtcError("invoice expiry は正の整数でなければなりません");
  }
  if (invoiceCreatedAt > settlementTime + skewSeconds) {
    return { ok: false, reason: "invoice_created_in_future" };
  }
  if (settlementTime > invoiceCreatedAt + invoiceExpirySeconds + skewSeconds) {
    return { ok: false, reason: "invoice_expired" };
  }
  return { ok: true };
}

/**
 * リプレイ項目を保持しなければならない下限時刻（Unix 秒）。仕様は
 * invoice_end + skew の 1 時間後までの保持を要求する。これより早く消すと
 * まだ検証を通る invoice が再利用できてしまう。
 */
export function replayRetainUntil({
  invoiceCreatedAt,
  invoiceExpirySeconds,
  skewSeconds = DEFAULT_SKEW_SECONDS,
}: Omit<ExpiryCheck, "settlementTime">): number {
  return invoiceCreatedAt + invoiceExpirySeconds + skewSeconds + 3600;
}

/** 金額はミリサトシの正の整数文字列。sats / BTC を混ぜると 1000 倍の事故になる。 */
export function assertMillisatoshiAmount(amount: string): string {
  if (!/^[1-9][0-9]*$/.test(amount)) {
    throw new LnbtcError(`amount はミリサトシの正の整数文字列でなければなりません: ${amount}`);
  }
  return amount;
}
