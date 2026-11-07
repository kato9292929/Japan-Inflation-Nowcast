// Delivery Receipt の公開鍵（keys[]・refetch_window_s・refetch_header）。仕様は https://github.com/kato9292929/delivery-receipt の docs/spec.md。
import { wellKnownResponse } from "@x402jp/delivery-receipt-seller";
import { receiptSeller } from "@/lib/receipts";

export const dynamic = "force-dynamic";

export const GET = async () => wellKnownResponse(receiptSeller());
