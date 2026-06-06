# Japan Inflation Nowcast

独立・日次・透明・エージェント可読な **日本のインフレ・ナウキャスト（速報）**。

> ## ⚠️ これは「公式 CPI」ではありません
> 本プロダクトは独立した **ナウキャスト（速報）** であり、総務省 CPI そのものでも公式統計
> でもありません。初期は **食料 + 住居の 2 コンポーネントのみ**で、CPI バスケットの一部
> （およそ 47%）しかカバーしません。すべての合成値には `coverage_pct`（「CPI バスケットの
> 約 X% をカバー」）を併記します。詳細は [`CLAUDE.md`](./CLAUDE.md) §0 と
> [`methodology/methodology.md`](./methodology/methodology.md) を参照。

## 何か

総務省 CPI（月次・遅延）と日経/渡辺 CPINow（会員制・T+2・閉じた箱）に対し、
**オープン方法論 + リアルタイム + x402 課金 + オンチェーン互換**で差別化する。

3 レイヤー（§1）:
1. 無償の人間向けダッシュボード（headline + coverage）。
2. x402 課金 JSON API（コンポーネント分解 / 中分類別 / 特売切替 / 全履歴 / bulk）。
3. 任意のオンチェーンフィード（Pyth / Chainlink 互換、testnet 先行）。

## セットアップ

```bash
# 依存解決（uv）
uv sync

# 環境変数
cp .env.example .env   # 編集する。.env はコミットしない。

# テスト
uv run pytest

# API 起動（Phase 6 以降に本体実装）
uv run uvicorn api.app:app --reload
```

ローカル検証は SQLite（`DATABASE_URL=sqlite:///./jin.db`）で可。本番は Postgres（§3）。

## 構成

| ディレクトリ | 役割 |
|--------------|------|
| `config/` | sources.yaml（既定空＝何も取得しない）/ baskets.yaml / normalize 辞書 |
| `scrapers/` | プラグイン式アダプタ + 遵守機構（base.py） |
| `storage/` | DB エンジン・SQLModel テーブル |
| `etl/` | 生 → clean（正規化・dedup・特徴量・ライフサイクル） |
| `index_engine/` | hedonic / laspeyres / flow / food / composite / aggregate |
| `api/` | FastAPI + x402 ゲート |
| `jobs/daily.py` | cron 単一エントリポイント |
| `methodology/` | 公開方法論 |
| `dashboard/`, `oracle/` | Phase 8（任意） |

## データ取り込み

2 経路を同じ adapter 登録の仕組みで扱う（どちらも `config/sources.yaml` が空なら何もしない安全既定）:

1. **スクレイピング**（`type: scrape`, 既定）: 下記ハード制約に従う。
2. **CSV 取り込み**（`type: csv`）: 公式統計（e-Stat 小売物価統計等）や手動パネルの
   ローカル CSV を**スクレイピング無し**で取り込む。HTTP・robots は使わない。運用者が
   `path`（CSV パス）と `column_map`（CSV 列名 → raw フィールド名）を記入する。各 CSV の
   利用規約・著作権・関連法の遵守は運用者責任（§8）。記入例は `config/sources.yaml` 参照。
3. **e-Stat API**（`type: estat`）: 政府統計 API から小売物価（価格・検証アンカー）や
   2020 年基準 CPI ウェイトを取得する。`appId` は `.env` の `ESTAT_APP_ID` に入れる。
   - **実 statsDataId の特定と live 取得は運用者の環境で行う**（このサンドボックス /
     CI からは `api.e-stat.go.jp` に出られないため、コードは実通信なしでモックテスト済み）。
     対象の `statsDataId`・品目/地域コードは運用者が appId で特定して `options` に pin する。
   - CPI 公式ウェイトの一括反映: `uv run jin-fetch-weights --stats-data-id <ID>` で
     `config/baskets.yaml` の `food.categories[*].weight` を**公式取得値**に書き換える
     （ハードコードしない）。利用規約・出典表示の遵守は運用者責任（§8）。

### 日次パネルと定点運用（食料）

食料の `food_raw` / `food_clean` は **(source, item_id, scrape_date) を natural key とする
日次パネル**。SKU ごとに 1 日 1 行を保持し、過去日のスナップショットを失わないため、
**固定基準日（base_date）に対する複数日 Jevons** が成立する。

CSV からの取り込み・バックフィル手順（開発／運用）:

```bash
# DB をクリーンに（任意。既存 DB は gitignore）
rm -f data/*.db

# 各日の CSV を scrape_date 付きで取り込む（日次パネルに追記）
uv run jin-import-csv data/life_basket_20260604.csv --date 2026-06-04
uv run jin-import-csv data/life_basket_20260605.csv --date 2026-06-05

# 指数を計算（base_date は .env / 環境変数 BASE_DATE で固定）
BASE_DATE=2026-06-04 uv run jin-daily --date 2026-06-05
```

`jin-daily` は食料を `food_incl_promo` / `food_excl_promo` の 2 系列で `index_values` に
保存する（合成 `JP-INFL-NOWCAST` は基調の `excl_promo` を採用）。matched-SKU が無い等で
値が NaN になる系列は保存をスキップ（DB を壊さない）。

## スクレイピング規約（重要・ハード制約 §8）

- `config/sources.yaml` が **空なら何も取得しない**安全既定。対象サイトは運用者が明示記入する。
- 起動時に **robots.txt を尊重**。レート制限（1 req/数秒）+ 指数バックオフ + 同時実行 1。
  User-Agent と問い合わせ先を明示。
- **生データは内部保存のみ。再配布・再公開しない。** 公開するのは派生集計（指数・統計）だけ。
- **各ソースの利用規約・著作権・関連法の遵守は運用者責任である。** コード側は法的判断をしない。

## ビルド状況

Phase 0（雛形）完了。構成・依存・データモデル・config スキーマ・TODO シグネチャ・pytest
スケルトンを用意。実装ロジックは未着手（§9 のフェーズ計画に従って 1 フェーズずつ進める）。

ライセンス: MIT。
