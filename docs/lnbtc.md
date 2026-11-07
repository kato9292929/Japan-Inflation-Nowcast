# x402 exact/lnbtc（Bitcoin Lightning）

`/api/jin/series`（12,000 msat = 12 sats）と `/api/jin/movers`（24,000 msat = 24 sats）は、Solana USDC に加えて Bitcoin Lightning でも払える。仕様は x402 本体の `specs/schemes/exact/scheme_exact_lnbtc.md`。ファシリテーターは別リポジトリ kato9292929/lnbtc-facilitator（`https://lnbtc.x402jp.com`）で、invoice の発行と支払い証明の検証・消費はそちらが行う。

## 流れ

1. 未払いの GET に、`withX402` が Solana の 402 を作る。JIN は実際のリクエストからリクエストハッシュ（http:1 プロファイル、bound header なし、公開オリジンは `PUBLIC_BASE_URL` で固定）を計算し、ファシリテーターの `/invoice` から invoice を取って、`PAYMENT-REQUIRED` の `accepts` に lnbtc を 1 件足す。1 秒で取れなければ lnbtc を外して Solana だけで返す
2. 支払った側は preimage を `payload.preimage` に入れ、`accepted` に lnbtc の項目をそのまま入れて、`PAYMENT-SIGNATURE` で再送する
3. JIN はリクエストハッシュを実行するリクエストから計算し直し（`accepted.extra.requestHash` は使わない）、ファシリテーターの `/settle` に送る。成功してからハンドラを実行し、`PAYMENT-RESPONSE` を付けて 200 を返す。upfront フローなので `/verify` は呼ばない
4. 消費後にハンドラが失敗したら `/credits` に記録して 503。同じ証明の再送が `duplicate_settlement` になったら `/credits/claim` を叩き、未提供分があれば 1 回だけ提供する

lnbtc の支払いは売り手ログ（`sales-log.ts`）と Delivery Receipt には記録しない。どちらも Solana の取引署名を前提にしているため。

## 実装

| ファイル | 中身 |
|---|---|
| `src/lib/jcs.ts`・`src/lib/lnbtc.ts` | RFC 8785 の正規化とリクエストバインディング（ブランチ `claude/sharp-ptolemy-076aoj` から lnbtc の部分だけを持ってきた） |
| `src/lib/lnbtc-config.ts` | 環境変数と msat 価格 |
| `src/lib/lnbtc-facilitator.ts` | ファシリテーターへの署名付きの呼び出し（`X-JIN-Signature`、署名対象は timestamp・method・path・body） |
| `src/lib/lnbtc-paywall.ts` | 402 への追加と、支払い付きの再送の処理 |
| `src/lib/x402-route.ts` | `withSolanaOnlyPaywall` から上の 2 つを呼ぶ |

## 環境変数（Vercel）

| 変数 | 値 |
|---|---|
| `LNBTC_ENABLED` | `true` のときだけ有効。既定は無効 |
| `LNBTC_FACILITATOR_URL` | `https://lnbtc.x402jp.com`（既定） |
| `LNBTC_HMAC_KEY_ID` | `jin-2026-11` |
| `LNBTC_HMAC_SECRET` | ファシリテーターの `/etc/lnbtc/facilitator.env` の `LNBTC_HMAC_KEYS` にある `jin-2026-11` の秘密。値はコミットしない |
| `LNBTC_PAY_TO` | phoenixd の nodeId（ファシリテーターの `LNBTC_PAY_TO` と同じ） |
| `LNBTC_NETWORK` | `mainnet`（既定） |

鍵・payTo のどれかが欠けていれば lnbtc は出さない（Solana だけで動く）。
