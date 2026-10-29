// サーバの起動時に Delivery Receipt の署名鍵を確かめる。RECEIPT_SIGNING_KEY が無ければ起動しない。
export async function register() {
  if (process.env.NEXT_RUNTIME !== "nodejs") return;
  const { receiptSeller } = await import("./lib/receipts");
  receiptSeller();
}
