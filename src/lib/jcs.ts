// RFC 8785（JSON Canonicalization Scheme）。lnbtc のリクエストバインディングは
// JCS 正規化 JSON の SHA-256 を BOLT11 の description hash にコミットするため、
// 正規化がずれると invoice とリクエストの照合が必ず失敗する。
// 仕様が要求する拒否条件（重複メンバ名・不正 Unicode・非有限数）は黙って通さない。

export class JcsError extends Error {}

// 孤立サロゲートは不正 Unicode。JSON.stringify は \udXXX として通してしまうので先に弾く。
function assertWellFormed(value: string): void {
  for (let i = 0; i < value.length; i += 1) {
    const code = value.charCodeAt(i);
    if (code >= 0xd800 && code <= 0xdbff) {
      const next = value.charCodeAt(i + 1);
      if (!(next >= 0xdc00 && next <= 0xdfff)) throw new JcsError("不正な Unicode（孤立サロゲート）");
      i += 1;
    } else if (code >= 0xdc00 && code <= 0xdfff) {
      throw new JcsError("不正な Unicode（孤立サロゲート）");
    }
  }
}

function serializeString(value: string): string {
  assertWellFormed(value);
  // JSON.stringify のエスケープは RFC 8785 の最短形と一致する（", \\, 制御文字）。
  return JSON.stringify(value);
}

function serializeNumber(value: number): string {
  if (!Number.isFinite(value)) throw new JcsError("有限数ではありません");
  // ECMAScript Number::toString。JSON.stringify は -0 を "0" にする（RFC 8785 と同じ）。
  return JSON.stringify(value);
}

/** JCS 正規化した JSON 文字列を返す。BOM も末尾改行も付けない。 */
export function canonicalize(value: unknown): string {
  if (value === null) return "null";
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "number") return serializeNumber(value);
  if (typeof value === "string") return serializeString(value);
  if (Array.isArray(value)) return `[${value.map(canonicalize).join(",")}]`;
  if (typeof value === "object") {
    const record = value as Record<string, unknown>;
    const keys = Object.keys(record);
    if (new Set(keys).size !== keys.length) throw new JcsError("重複したメンバ名");
    if (keys.some((key) => record[key] === undefined)) throw new JcsError("undefined は JCS の対象外");
    // メンバは UTF-16 コードユニット順（JS の既定文字列比較と一致）。
    const members = [...keys]
      .sort()
      .map((key) => `${serializeString(key)}:${canonicalize(record[key])}`);
    return `{${members.join(",")}}`;
  }
  throw new JcsError(`JCS のデータモデル外の型: ${typeof value}`);
}

/** JCS 正規化結果の UTF-8 バイト列。description hash の入力そのもの。 */
export function canonicalBytes(value: unknown): Buffer {
  return Buffer.from(canonicalize(value), "utf8");
}
