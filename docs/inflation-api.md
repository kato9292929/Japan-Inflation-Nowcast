# 多国インフレAPI

公的CPIの保存済みJSONを配信する。日本だけ既存のJIN店頭観測指数を併記する。
予測、採点、民間POS、時系列APIは含まない。店頭指数の計算・基準日は変更しない。

## 配信

- `GET /api/inflation/latest`: `{ "countries": [jp, kr, sg] }`。常に無料。
- `GET /api/inflation/jp`、`kr`、`sg`: 上記配列の要素と同じ国別オブジェクト。
- 非対応国はCORS付き404。保存ファイルの欠落・形式不正はCORS付き503。
- 初期状態はすべて無料・CORS open。リクエストから統計APIへの通信は行わない。
- `data/inflation/{country}.json` はリクエスト時に読み直す。Next.jsのファイル追跡に含める。
  不変デプロイ環境では更新したJSONを含めて再デプロイする。永続ディスクの環境では
  配信プロセスが参照する同じディレクトリで更新する。

## フィールド

| フィールド | 意味 |
| --- | --- |
| `country`, `source`, `source_url` | 国コード、公的出典、公式ページ |
| `as_of` | 公表対象月、`YYYY-MM`。未取得はnull |
| `released_at` | 対象月の公表日。確認できない場合null。API更新日を代用しない |
| `fetched_at` | 最後に値の取得が成功したUTC日時。失敗では更新しない |
| `cpi_yoy`, `food_yoy` | 前年同月比、パーセント単位（2は2%） |
| `cpi_index` | `value`、`base_year`、`base_value`（100）。未取得の基準年はnull |
| `metric_status` | 指標ごとの `available` / `not_fetched` / `not_supported` |
| `yoy_method` | `published` は公表値、`index_ratio` は同一基準の指数から算出 |
| `status` | `not_fetched` / `ok` / `refresh_failed` |
| `stale`, `stale_reasons` | 配信時点での鮮度判定と機械可読な理由 |
| `last_attempt_at`, `last_error` | 最後の更新試行日時と固定エラーコード。秘密情報は含めない |

韓国は総合指数の当月／前年同月の比率から `(当月 / 前年同月 - 1) * 100` を計算し、
小数点以下6桁に丸める。公表された前年比と丸め差があり得るため `index_ratio` と明示する。
韓国の食料はこのアダプタでは未対応（`not_supported`、null）。未対応だけではstaleにしない。
日本・シンガポールは総合・食料の公表前年比を取得する。取得対象の欠測・曖昧な系列・
基準年の不一致・APIエラーでは更新全体を失敗扱いにする。

日本の `store_index` は `excl_promo` / `incl_promo` / `base_date` / `as_of`（観測日）を
`src/data/jin_public.json` からそのまま取得する。`generated_at` はファイル生成日時。
単一店舗の非公的観測であることを `type`、`official_cpi`、`scope`、
`geographically_representative` で区別する。レスポンスに説明文は含めない。

## 鮮度の判定

公的CPIは以下のいずれかでstaleとなる。閾値は運用上の期限であり、公表予定日の保証ではない。

- 未取得、更新失敗、取得対象指標の欠測、保存時のstale指定。
- `fetched_at` から7日超。
- 対象月の翌月1日00:00 UTCから62日超。
- 取得日時または対象月が未来。

店頭指数は観測日の日本時間00:00から3日超、値の欠落、未来の観測日でstaleとなる。
公的CPIと店頭指数のstaleは独立。国のトップレベルstaleは公的CPIだけを表す。
公開JSONの初期値は捏造せずすべてnull。`released_at` の収集はTODO。

## リフレッシュ

Python 3.12以上とuvを使い、リポジトリ直下で実行する。

```sh
uv sync
# シェルまたは運用側の秘密管理機構から環境変数を設定する。
# .envは本コマンドでは自動ロードしない。
uv run jin-refresh-inflation --country jp
uv run jin-refresh-inflation --country kr
uv run jin-refresh-inflation --country sg
# 全対象国を順に実行。1か国でも失敗すれば終了コード1。
uv run jin-refresh-inflation
```

日本は `ESTAT_APP_ID`、韓国は `KOSIS_API_KEY` と `KOSIS_CPI_REGION_CODE` が必要。
シンガポールはキー不要。`--output-dir PATH` で検証用出力先を分離できる。
国ごとに同じディレクトリの一時ファイルから原子的に置換する。
失敗時は過去値と取得日時を保持し、`refresh_failed` とstaleを保存する。
標準エラーにも失敗を出し、成功終了として扱わない。次の成功で失敗状態を解除する。
APIキーを含むURLや応答本文はログに出さない。

同じ出力先での同時実行は `.refresh.lock` により拒否する。強制終了後にロックが残った場合は、
他の更新処理が動いていないことを確認してから削除する。公開3ファイル以外はgit追跡しない。

## 確認した公式仕様（2026-09-17）

### 日本

- [e-Stat API 3.0仕様](https://www.e-stat.go.jp/api/api-info/e-stat-manual3-0)
- [2025年基準CPI、統計表0004052037](https://www.e-stat.go.jp/stat-search/database?statdisp_id=0004052037)
- `https://api.e-stat.go.jp/rest/3.0/app/json/getMetaInfo` の `appId` / `statsDataId` /
  `lang=J`。`GET_META_INFO.METADATA_INF.CLASS_INF.CLASS_OBJ` で全国・総合・食料・
  指数・前年同月比・月次時間軸を照合する。コードを推測して固定しない。
- 同じベースURLの `getStatsData` に `cdArea` / `cdCat01` / `cdTab` / `cdTime` を指定。
  直近18か月に限定し、`GET_STATS_DATA.STATISTICAL_DATA.DATA_INF.VALUE` の属性と `$` を読む。
  単一要素の辞書も扱う。想定外の継続データ（`RESULT_INF.NEXT_KEY`）は失敗にする。

### 韓国

- [KOSIS統計資料API](https://kosis.kr/openapi/devGuide/devGuide_0201List.do)
- [KOSIS公式サイト掲載のCPI応答例と案内](https://kosis.kr/civilComplaint/qnaDetail.do?boardIdx=22500)
- `https://kosis.kr/openapi/Param/statisticsParameterData.do` に `method=getList` /
  `apiKey` / `orgId=101` / `tblId=DT_1J22003` / `itmId=T` / `objL1` /
  `prdSe=M` / `newEstPrdCnt=13` / `format=json` / `jsonVD=Y`。
- 応答は配列。`PRD_DE` がYYYYMM、`DT` が値、`UNIT_NM` が基準、`C1_NM` が地域。
  全国名 `전국` と指定コードの両方を照合。年次・他地域・余分な分類を混ぜない。
- TODO: 運用者のKOSIS「統計表選択→URL生成」でこの表の全国コードを確認し、
  `KOSIS_CPI_REGION_CODE` を設定する。公式資料で未確認の地域コードは実装に埋めない。

### シンガポール

- [SingStat Developer API](https://tablebuilder.singstat.gov.sg/view-api/for-developers)
- [公式OpenAPI仕様](https://tablebuilder.singstat.gov.sg/view-api/for-developers/openapi)
- [月次指数 M213751](https://tablebuilder.singstat.gov.sg/table/TS/M213751)
- [月次前年比 M213781](https://tablebuilder.singstat.gov.sg/table/TS/M213781)
- `https://tablebuilder.singstat.gov.sg/api/table/metadata/{id}` の `Data.records` で
  表題・2024年基準・Monthly・出典・All Items／Foodの系列・単位・`endPeriod` を照合。
- `tabledata/{id}` の `seriesNoORrowNo` / `timeFilter` / `limit` を指定。
  `Data.row[].columns[].key/value` を読む。月次キーは `2026 Jul` の形式。
- `StatusCode`、系列番号、対象月、単位を検証。指数表と前年比表の対象月が違えば失敗。
  User-AgentとAcceptヘッダを設定する。

## 検証と残作業

```sh
npm ci
npm run typecheck
npm test
uv run pytest
```

テストのAPI応答は公式仕様に沿った合成データ。実取得成功の証拠とは分ける。
2026-09-17にSingStatの実アダプタで2026年7月分の指数・総合前年比・食料前年比を
検証用ディレクトリへ取得できた。配信対象の初期JSONはnullのまま。
TODO: 日本・韓国の実ライブ取得、韓国全国コードの確認、各国の配信JSONへの実データ反映。
TODO: 本番ネットワークでの決済・精算の確認。
