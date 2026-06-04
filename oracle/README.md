# oracle/ — オンチェーンフィード（任意, §1, Phase 8）

最新の合成ナウキャスト値（`JP-INFL-NOWCAST`）を Pyth / Chainlink 互換で publish する
（testnet 先行）。**既定は無効** — `ORACLE_RPC_URL` / `ORACLE_PRIVATE_KEY` /
`ORACLE_CONTRACT` の 3 つが揃ったときだけ実送信する。

- `oracle/publisher.py`: payload 構築（`build_payload`）と Pyth 互換エンコード
  （`encode_payload`: 整数 price + expo=-8、coverage は bps、date は YYYYMMDD）。
  `publish` / `publish_latest` は鍵等が無ければ **skip して落ちない**。web3 クライアントは
  注入可能で、本リポジトリのテストは payload/encode のみ（**実送信はテストしない**）。
- `oracle/web3_client.py`: web3 ベースの参照クライアント（運用者が ABI / 関数を pin して実装）。
  web3 は遅延 import（オプション依存 `uv sync --extra oracle`）。

publish される値も部分カバーのナウキャストである旨を `coverage_pct`・`methodology_version`
としてメタデータに含める（§0）。**実 publish は運用者環境（testnet 先行）で行う。**

`jobs/daily.py` の最後に任意ステップとして `publish_latest` を呼ぶが、env が未設定なら
スキップされる（既定無効）。
