# delivery-receipt（取り込み版）

`kato9292929/delivery-receipt` の `packages/seller/src`（Express 用アダプタを除く）と `packages/verify/src/index.ts`（`verify.ts`）を、コミット 915d02e の時点でそのまま取り込んだもの。変更は import の書き換えだけ（`@delivery-receipt/verify` → `./verify`、`.js` 拡張子を外す）。

直すときは delivery-receipt 側で直してから取り込み直す。ここだけを書き換えない。
仕様は delivery-receipt の `docs/spec.md`。
