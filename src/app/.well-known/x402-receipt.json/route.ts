// Delivery Receipt の公開鍵（keys[]・refetch_window_s・refetch_header）。仕様は src/lib/delivery-receipt/README.md。
import { wellKnownResponse } from "@/lib/delivery-receipt";
import { receiptSeller } from "@/lib/receipts";

export const dynamic = "force-dynamic";

export const GET = async () => wellKnownResponse(receiptSeller());
