# Macro reference series (CGPI)

JIN の日次ナウキャストと並べる公的月次統計の reference。第一弾は日銀 企業物価指数（CGPI）
国内企業物価指数・総平均（level 2020=100 と前年比 yoy_pct）。

- ストア: `data/macro_reference.parquet`（`.gitignore` 配下。GitHub Actions が force-add で PR 反映）
- 取得: `python scripts/fetch_cgpi.py [--full] [--source mtshtml|bulk|PATH]`
- 参照: `lib.macro_reference.get_latest_value("cgpi_total", "yoy_pct")` →
  `{"period": date(2026,5,1), "value": 6.3, "release_type": "mtshtml", ...}`

## 検証済みの事実（2026-06-11 確認）

- **primary = ソース A（mtshtml HTML）**: `https://www.stat-search.boj.or.jp/ssi/mtshtml/pr01_m_1.html`
  - 認証不要・静的 URL。単一 HTML テーブル。ヘッダ部に Name / Series code / Unit /
    Start / End / Last update のメタ行、その下に `YYYY/MM` 行ラベルの月次データ。欠損は `ND`。
  - level と yoy が日銀側で計算済みの列として取得できる（自前計算不要）。
  - 使用系列コード:
    - 国内総平均 (2020=100): `PR01'PRCG20_2200000000`
    - 国内総平均 前年比 (%): `PR01'PRCG20_2200000000%`
  - 依存は `pandas.read_html` + `lxml` のみ。
- 改訂: 日銀は直近数ヶ月を訂正値(r)で遡及改訂する。`period` を自然キーに含め、再取得で
  同一 period の値を**上書き**する設計（`lib.macro_reference.upsert`、テストで担保）。
- 2026-06-10 公表（2026年5月速報）の実測値で fixture を作成。例: 2026/05 = 134.5 / +6.3%、
  2026/04 = 133.3 / +5.3%（訂正値）。

## 未確認事項

- **ソース B（一括 zip CSV）**: `https://www.stat-search.boj.or.jp/info/cgpi_m_jp.zip`
  の zip 内 CSV フォーマットは**実物未確認**（メタ行複数・横持ち・Shift-JIS の可能性）。
  `scripts/fetch_cgpi.py --source bulk` は **NotImplementedError**（TODO）。実物確認後に実装する。
- **mtshtml の live 取得**は当サンドボックスから到達不可（`stat-search.boj.or.jp` 未達）のため
  **未確認**。本 PR の検証は committed HTML fixture（`tests/fixtures/cgpi_mtshtml_sample.html`、
  実ページの構造を再現）に対する parse テストのみ。**live で動いたとは主張しない。**

## 手動確認手順（live）

1. GitHub Actions の `fetch-macro-monthly` を **workflow_dispatch** で手動実行
   （cron は `23 0 * * *` UTC のまま）。
2. ワークフローは `pip install -r requirements.txt` → `python scripts/fetch_cgpi.py` を実行し、
   `data/macro_reference.parquet` に差分があれば `peter-evans/create-pull-request` で PR を作る。
3. ローカル確認は（ネットワークがある環境で）:
   ```bash
   python scripts/fetch_cgpi.py --full      # live mtshtml から24ヶ月
   python -c "from lib.macro_reference import get_latest_value as g; print(g('cgpi_total'))"
   ```
   フォーマットが変わっている場合 `parse_mtshtml_table` が `ValueError` を raise し、Actions
   ログで検知できる。

## 次フェーズ候補（今回スコープ外）

CGPI が live で動いてから着手。日銀 分析データ（`https://www.boj.or.jp/research/research_data/`）の
機械可読データ: 消費者物価コア指標（刈込平均・加重中央値・最頻値）/ 消費活動指数 / 需給ギャップ・
潜在成長率 / 実質輸出入。URL・フォーマットは未確認なので着手時に実物を確認してから実装する。
