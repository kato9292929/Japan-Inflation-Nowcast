// Delivery Receipt（kato9292929/delivery-receipt、src/lib/delivery-receipt に取り込み）の配線。
// 有料の 200 に X-Delivery-Receipt（Ed25519 の署名付きレシート）を付け、X-Payment-Refetch 付きの
// 再取得には決済を走らせずに保存済みの本文を返す。
//
// 署名鍵は RECEIPT_SIGNING_KEY（必須。無ければこのモジュールの読み込みで止まり、有料ルートは動かない）。
// 保存先は売り手ログと同じ Upstash Redis（SALES_LOG_KV_REST_URL / _TOKEN、キーは receipt:*）。
// 未設定、または RECEIPT_STORE=file ならファイル保存（RECEIPT_STORE_DIR、既定 /tmp/jin-receipts。
// Vercel ではインスタンスごとに消えるので本番は Upstash を使う）。
import { FileStore, UpstashStore, createReceiptSeller, type ReceiptSeller } from "./delivery-receipt";

function store() {
  if (process.env.RECEIPT_STORE === "file") return new FileStore(process.env.RECEIPT_STORE_DIR ?? "/tmp/jin-receipts");
  const url = process.env.SALES_LOG_KV_REST_URL;
  const token = process.env.SALES_LOG_KV_REST_TOKEN;
  if (url && token) return new UpstashStore({ url, token, keyPrefix: "receipt:" });
  return new FileStore(process.env.RECEIPT_STORE_DIR ?? "/tmp/jin-receipts");
}

let seller: ReceiptSeller | null = null;

/** 初回の呼び出しで作る（RECEIPT_SIGNING_KEY が無ければ投げる）。 */
export function receiptSeller(): ReceiptSeller {
  seller ??= createReceiptSeller({ store: store() });
  return seller;
}
