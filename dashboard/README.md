# dashboard/ — 無償 headline 表示（§1, Phase 8）

合成ナウキャストの headline（最新値 + 直近 90 日 + coverage + disclaimer）を無償で見せる
読み取り専用ビュー。

- 描画ロジック: `dashboard/render.py`（純粋関数 `build_headline_view` / `render_html` /
  `coverage_label`）。無償 API レスポンス形を入力に取り、実通信はしない。
- 配信: API の `GET /dashboard`（HTML を返す）。無償 API（`/v1/indices/JP-INFL-NOWCAST/latest`
  と `/history`）を内部参照する。

> **誤認防止（§0）:** 「総務省の公式統計とは異なる部分カバーのナウキャスト（速報）」
> である旨と `coverage_pct`（必ず 100% 未満）を画面に必ず出す。「公式 CPI」「CPI そのもの」
> と誤認させる表記は入れない。

live 配信（ホスティング・CDN 等）は運用者環境で行う。
