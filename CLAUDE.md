# CLAUDE.md — Japan Inflation Nowcast

このファイルはリポジトリ直下に置く。Claude Code はこれをプロジェクトメモリとして読む。チャット履歴は無いので、ビルドに必要な設計判断はすべてこのファイルに自己完結で書いてある。

## 使い方（Claude Code への投げ方）

1. 空リポジトリにこの CLAUDE.md を置く。
2. Claude Code を起動し、末尾の「起動プロンプト」を最初のメッセージとして貼る。
3. 以降は「Phase N を実装して」と1フェーズずつ進める。各フェーズには受け入れ条件があるので、満たされたか確認してから次へ。
4. データソースと x402 facilitator 設定は私（運用者）が `config/` に入れる。Claude は具体的なスクレイピング対象サイトを勝手に決めず、プラグイン式アダプタの枠だけ作る。

## 0. これは何か（背景と非交渉の制約）

独立・日次・透明・エージェント可読な「日本のインフレ・ナウキャスト（速報）」を作る。総務省 CPI（月次・遅延）と日経/渡辺 CPINow（会員制・T+2・閉じた箱）に対し、オープン方法論 + リアルタイム + x402 課金 + オンチェーン互換で差別化する。Truflation の物価オラクルの日本版にあたる。

非交渉の制約（最重要。コード・ドキュメント・API・UI のどこでも破らない）:

* これは「公式 CPI」ではなく「ナウキャスト/速報」である。"CPI そのもの" "公式" と誤認させる表記を一切しない。
* 初期は食料 + 住居の2コンポーネントのみ。合成は CPI バスケットの一部（およそ 47%）しかカバーしない。値には必ず coverage_pct を付け、front 表記に「CPI バスケットの約 X% をカバー」を明示する。
* 生の単純平均は構成バイアスで無効。必ず品質調整/指数算式を使う（後述）。
* スクレイピングは各ソースの利用規約・robots.txt・著作権・関連法を運用者責任で遵守。生データは再配布せず、派生集計（指数・統計）のみ公開。アダプタはこれらの遵守機構を内蔵する。
* 透明性が唯一最大の差別化。methodology は第三者が再現できる粒度で公開する。盛らない。

## 1. プロダクトの形（3 レイヤー）

1. 無償の人間向けダッシュボード: 合成ナウキャストの headline（日次・直近 90 日）+ coverage 表示。
2. x402 課金 JSON API: コンポーネント分解、中分類別、特売 incl/excl 切替、全履歴、bulk。per-call USDC（Base）。
3. 任意のオンチェーンフィード: 最新合成値を Pyth / Chainlink 互換で publish（既存 x402 Oracle 経路に合わせる、testnet 先行）。

## 2. インデックスコード

* `JP-INFL-NOWCAST` … 合成（部分カバー）
* `JP-INFL-FOOD` … 食料コンポーネント
* `JP-INFL-HOUSING` … 住居コンポーネント（募集賃料ベース）
* 各コンポーネントは派生系列を持つ（後述）。

## 3. 技術スタックと規約

* Python 3.12、依存管理 uv。
* DB: Postgres（SQLModel / SQLAlchemy）。ローカル検証は SQLite 可。
* スクレイピング: httpx + selectolax、必要時のみ playwright。
* 指数計算: pandas, numpy, statsmodels, scikit-learn。
* API: FastAPI。設定は pydantic-settings（.env）。
* スケジューラ: cron から `jobs/daily.py` を叩く単一エントリポイント。
* 識別子・関数名・カラムは英語。コメント・docstring は日本語可。
* すべて冪等（同日再実行で二重計上しない）。乱数・時刻依存はテスト可能に分離。
* 秘密情報は .env のみ、コミット禁止（.gitignore / .env.example を用意）。

## 4. リポジトリ構成

```
.
├─ CLAUDE.md
├─ pyproject.toml / uv.lock
├─ .env.example
├─ config/
│   ├─ sources.yaml          # スクレイピング対象（運用者が記入。既定は空＝何も取得しない）
│   ├─ baskets.yaml          # 代表バスケット・中分類・CPIウェイト・基準期
│   └─ normalize/            # ward/station/住所 正規化辞書
├─ scrapers/
│   ├─ base.py               # 抽象アダプタ（robots/レート制限/バックオフ内蔵）
│   ├─ housing/              # 住居ソースアダプタ（プラグイン）
│   └─ food/                 # 食料ソースアダプタ（プラグイン）
├─ storage/
│   ├─ db.py
│   └─ models.py             # listings_raw, food_raw, clean tables, index_values, methodology_versions
├─ etl/
│   ├─ housing.py
│   └─ food.py
├─ index_engine/
│   ├─ hedonic.py            # 住居 主系列
│   ├─ laspeyres.py          # 住居/食料 透明クロスチェック
│   ├─ flow.py               # 住居 新規フロー
│   ├─ food.py               # 食料 Jevons + 上位ラスパイレス + 特売処理
│   ├─ composite.py          # 合成 + coverage
│   └─ aggregate.py          # 平滑化・YoY/MoM/WoW・出力整形
├─ api/
│   ├─ app.py
│   └─ x402.py               # 402 ゲーティング（既存 facilitator 設定を再利用）
├─ jobs/
│   └─ daily.py              # scrape → etl → index → composite → validate
├─ methodology/
│   └─ methodology.md        # 公開する方法論（自動 + 手動更新）
├─ dashboard/                # 無償 headline 表示（Phase 8）
├─ oracle/                   # Pyth/Chainlink 互換 publish（Phase 8）
└─ tests/
```

## 5. データモデル（要点）

* `listings_raw`（住居）/ `food_raw`（食料）: 生取得。ライフサイクル first_seen / last_seen / is_active を更新。
* 住居フィールド: listing_id, source, scrape_date, first_seen, last_seen, ward, address_norm, station, walk_min, rent_total, mgmt_fee, area_m2, madori, build_year, floor, structure, deposit, key_money。
* 食料フィールド: item_id, source, scrape_date, first_seen, last_seen, category(=CPI食料中分類), product_name, brand, unit, unit_size, price, is_promo, in_stock。
* `*_clean`: 正規化・dedup・特徴量済み。
* `index_values`: index_code, date, freq, value, base_value, base_date, yoy_pct, mom_pct, wow_pct, n, n_new, series_type, coverage_pct, promo_mode, components(JSON), smoothing_window_days, methodology_version。
* `methodology_versions`: version, effective_date, formula_notes, weights_source, changelog。

## 6. 方法論（厳密に実装する）

### 6-1. 住居（JP-INFL-HOUSING）

* 主系列 = 回転ヘドニック + 代表バスケット予測:
   * 直近 28 日ローリング窓の active 募集で `ln(rent_total)` を特徴量（log_area, ward, age_band, walk_band, floor, structure, madori）に OLS 回帰。
   * `config/baskets.yaml` の代表ユニット群（ward × madori の固定スペック + ストック構成ウェイト）の賃料を予測。基準期予測値に対する比 × 100 を指数化。
* クロスチェック = 層別ラスパイレス（ward × madori × age_band × walk_band の中央 ¥/m² を基準期固定ウェイトで加重）。主系列との乖離を監視値に記録。
* フロー = 新規掲載の中央 ¥/m²（層別補正のみ、先行シグナル）。
* 「募集賃料ベースの住居インフレ速報。帰属家賃の厳密推計はしない」と methodology に明記。

### 6-2. 食料（JP-INFL-FOOD）

* 基礎集計（elementary）= 同一 SKU の価格相対（当日 price / 基準期 price）の幾何平均（Jevons）。中分類ごとに算出。
* 上位集計 = 中分類を `config/baskets.yaml` の CPI 食料ウェイトでラスパイレス加重。
* 特売 = incl_promo と excl_promo の2系列（excl は is_promo 除外、または最頻値寄せ）。基調は excl。
* SKU 入れ替わり = 消失/新規をチェーン接続で連続化。基準期に無い新規 SKU は次期から組入れ。

### 6-3. 合成（JP-INFL-NOWCAST）

* FOOD と HOUSING を CPI 費目ウェイト（食料・住居）で正規化加重。
* `series_type="composite_partial"`、`coverage_pct`（=食料+住居の CPI ウェイト合計）、`components`（code, weight, value, yoy）を付与。
* ウェイトは `config/baskets.yaml`（出典: 総務省 CPI 基準年）から読み、リベースで version 更新。
* 合成に使う食料系列は promo_mode で切替（既定 excl_promo）。

### 6-4. 共通

* 平滑化 7 日 / 28 日。YoY/MoM/WoW、n、信頼区間/件数を併記。
* すべての値に base_date, methodology_version を紐付け。

## 7. API と x402

* エンドポイント: `/v1/indices`, `/v1/indices/{code}/latest`, `/v1/indices/{code}/history`, `/v1/indices/{code}/components`, `/v1/indices/{code}/wards`, `/v1/methodology`, `/v1/indices/{code}/bulk`。
* 無償: `JP-INFL-NOWCAST` の headline（latest + 直近 90 日）+ coverage_pct。
* x402 ゲート: コンポーネント分解、中分類別、ward 別、incl/excl promo 切替、90 日超 history、bulk。
* x402: 既存ミドルウェア/facilitator を再利用する前提のフックを用意。なければ 402 応答に payment requirements（USDC, Base, amount, recipient, facilitator URL）を返し、X-PAYMENT を検証してから本体を返す標準フローを実装。価格は config 化。
* JSON は §5 の値オブジェクト形に統一。OpenAPI 自動生成、例付き。

## 8. 法務・スクレイピング規約（ハード制約）

* 起動時に robots.txt を取得・尊重。不許可パスは取得しない。
* レート制限（1 req/数秒）+ 指数バックオフ + 同時実行 1。User-Agent と問い合わせ先を明示。
* `config/sources.yaml` が空なら何も取得しない（既定で安全側）。対象サイトは運用者が明示的に記入する。
* 生データは内部保存のみ。再配布・再公開しない。公開するのは派生集計だけ。
* 各ソースの規約・著作権・関連法の遵守は運用者責任である旨を README とアダプタ冒頭に明記。法的判断はコード側で行わない。

## 9. ビルド計画（フェーズと受け入れ条件）

各フェーズ完了時にテストが通り、受け入れ条件を満たすこと。

* Phase 0 — 雛形: 構成・依存・models・config スキーマ・.env.example・README。実装は TODO シグネチャのみ。受け入れ: `uv run` で起動、`pytest` がスケルトンで緑。
* Phase 1 — 住居スクレイパ + ETL: base.py（遵守機構内蔵）、housing アダプタ枠、etl/housing.py（正規化・dedup・特徴量・ライフサイクル）。受け入れ: ダミー固定 HTML フィクスチャから listings_clean が生成、冪等。
* Phase 2 — 住居指数: hedonic + laspeyres + flow + aggregate。受け入れ: 合成データで「価格一律 +5% → 指数 +5%」「構成だけ変化 → 指数不変（構成バイアス耐性）」のテストが通る。
* Phase 3 — 食料スクレイパ + ETL: food アダプタ枠、etl/food.py（SKU 名寄せ・ライフサイクル・単価正規化）。受け入れ: フィクスチャから food_clean、同一 SKU を時系列で追跡できる。
* Phase 4 — 食料指数: food.py（Jevons + 上位ラスパイレス + incl/excl promo + SKU 入替チェーン）。受け入れ: 「同一 SKU +5% → 指数 +5%」「SKU ミックスのみ変化 → 不変」「特売除外で系列が変わる」テスト。
* Phase 5 — 合成: composite.py + coverage。受け入れ: components とウェイトから合成が再現でき、coverage_pct が正しく、表記に「公式 CPI」誤認が無いことを検査するテスト。
* Phase 6 — API + x402: 全エンドポイント、無償/有償境界、402 フロー、OpenAPI。受け入れ: 無償は headline のみ返し、ゲート対象は支払い無しで 402、検証後 200。
* Phase 7 — methodology + 検証 + cron: methodology.md 生成、jobs/daily.py、バックテスト（食料 YoY ↔ 総務省「食料」、住居 ↔「民営家賃」、合成 ↔「食料+住居」加重）。受け入れ: daily.py が全段を順に実行し部分復旧でき、検証レポートが出る。
* Phase 8（任意）— dashboard + oracle: 無償 headline 表示（積み上げ内訳・総務省比較チャート・coverage コピー）、Pyth/Chainlink 互換 publish（testnet）。

## 10. 環境変数（.env.example に用意）

* DATABASE_URL
* X402_FACILITATOR_URL, X402_RECIPIENT_ADDRESS, X402_CHAIN（base）, X402_ASSET（usdc）
* SCRAPER_USER_AGENT, SCRAPER_CONTACT
* BASE_DATE（基準期）, REBASE_POLICY
