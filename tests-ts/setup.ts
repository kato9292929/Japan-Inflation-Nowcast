// テスト用の Delivery Receipt 鍵と保存先（毎回その場で作る使い捨て。本番の鍵ではない）。
import { randomBytes } from "node:crypto";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

process.env.RECEIPT_SIGNING_KEY ??= randomBytes(32).toString("base64url");
process.env.RECEIPT_STORE = "file";
process.env.RECEIPT_STORE_DIR = mkdtempSync(join(tmpdir(), "jin-receipts-"));
