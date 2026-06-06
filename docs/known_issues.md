# Known Issues

## 住居（HousingRaw / HousingClean）の上書き問題 — 次回対応

食料（FoodRaw / FoodClean）は Phase 9 で **日次パネル化**（natural key を
`(source, item_id, scrape_date)` にし、SKU ごとに 1 日 1 行を保持）して、固定基準日に
対する複数日の指数計算を可能にした。

**住居側（`ListingRaw` / `ListingClean`）には同等の修正をまだ入れていない。**

- `etl/housing.py:upsert_raw` は `(source, listing_id)` をキーに既存行を引き、
  `scrape_date` を当日に上書きする（SKU = 物件ごとに 1 行のみ保持）。
- `etl/housing.py:run` も clean を「最新 scrape_date 採用」で再構築する。
- 住居の主系列はヘドニック（28 日ローリング窓を `_window` で date 範囲抽出）なので、
  日々上書きすると**窓内の過去日の募集が失われ**、ローリング推定が当日だけに退化する。
  food と同様に複数日分の観測がパネルとして残らない。

### 対応方針（食料と対称）

1. `storage/models.py`: `ListingRaw` / `ListingClean` に
   `UniqueConstraint("source", "listing_id", "scrape_date")` と
   `Index("...", "source", "scrape_date")` を追加。
2. `etl/housing.py`: `upsert_raw` の冪等キーを `(source, listing_id, scrape_date)` に変更、
   `_recompute_lifecycle` 相当で first_seen/last_seen/is_active を SKU 単位に整合。
   `run` は raw 全行を clean に 1:1 投影（dedup 撤廃）。
3. テスト: 28 日窓に複数日の募集が残り、ヘドニックが窓全体で推定されることを検証。

### スコープ

本件は **Phase 9（食料パネル化）のスコープ外**。次回の住居タスクで対応する。
それまで住居指数の複数日運用は未サポート（単一日の trivial 100 のみ動作）。
