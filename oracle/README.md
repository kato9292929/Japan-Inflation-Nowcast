# oracle/ — オンチェーンフィード（Phase 8・任意）

最新の合成ナウキャスト値を Pyth / Chainlink 互換で publish する（testnet 先行, §1, §9 Phase 8）。
既存の x402 Oracle 経路に合わせる。

予定（§9 Phase 8）:
- 最新 `JP-INFL-NOWCAST` 値を Pyth / Chainlink 互換フォーマットで publish。
- testnet で先行検証してから本番。

> publish する値も部分カバーのナウキャストである旨（coverage）をメタデータに含める（§0）。

Phase 8 着手まで実装は置かない。
