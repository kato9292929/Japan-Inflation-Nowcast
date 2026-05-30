# Methodology — Japan Inflation Nowcast

> **これは「公式 CPI」ではありません。** 本プロダクトは独立・日次の **ナウキャスト（速報）**
> であり、総務省 CPI そのものでも公式統計でもありません（CLAUDE.md §0 非交渉制約）。
> 初期は **食料 + 住居の 2 コンポーネントのみ**で、CPI バスケットの一部（およそ 47%）しか
> カバーしません。すべての合成値には `coverage_pct` を併記します。

透明性が唯一最大の差別化（§0）。この文書は第三者が再現できる粒度で公開する。盛らない。
この文書は一部自動生成・一部手動更新（§9 Phase 7）。

## インデックスコード（§2）

| code | 内容 |
|------|------|
| `JP-INFL-NOWCAST` | 合成（部分カバー, `composite_partial`） |
| `JP-INFL-FOOD` | 食料コンポーネント |
| `JP-INFL-HOUSING` | 住居コンポーネント（募集賃料ベース） |

## 住居 JP-INFL-HOUSING（§6-1）

- **主系列 = 回転ヘドニック + 代表バスケット予測。** 直近 28 日ローリング窓の active 募集で
  `ln(rent_total)` を特徴量（log_area, ward, age_band, walk_band, floor, structure, madori）に
  OLS 回帰し、`config/baskets.yaml` の代表ユニット群の賃料を予測。基準期予測値に対する比 × 100。
- **クロスチェック = 層別ラスパイレス**（ward × madori × age_band × walk_band の中央 ¥/m² を
  基準期固定ウェイトで加重）。主系列との乖離を監視値に記録。
- **フロー = 新規掲載の中央 ¥/m²**（層別補正のみ、先行シグナル）。
- **注記:** 募集賃料ベースの住居インフレ速報。帰属家賃の厳密推計はしない。

## 食料 JP-INFL-FOOD（§6-2）

- **基礎集計（elementary）= Jevons**: 同一 SKU の価格相対（当日 / 基準期）の幾何平均。中分類ごと。
- **上位集計 = ラスパイレス**: 中分類を `config/baskets.yaml` の CPI 食料ウェイトで加重。
- **特売**: `incl_promo` / `excl_promo` の 2 系列。基調は `excl_promo`。
- **SKU 入れ替わり**: 消失/新規をチェーン接続で連続化。基準期に無い新規 SKU は次期から組入れ。

## 合成 JP-INFL-NOWCAST（§6-3）

- FOOD と HOUSING を CPI 費目ウェイト（食料・住居）で正規化加重。
- `series_type="composite_partial"`、`coverage_pct`（=食料+住居の CPI ウェイト合計）、
  `components`（code, weight, value, yoy）を付与。
- 合成に使う食料系列は `promo_mode` で切替（既定 `excl_promo`）。

## 共通（§6-4）

- 平滑化 7 日 / 28 日。YoY / MoM / WoW、観測件数 `n`、信頼区間/件数を併記。
- すべての値に `base_date`, `methodology_version` を紐付ける。

## バージョン台帳

方法論の変更・リベースは `methodology_versions` テーブル（§5）に version を起こして記録する。

| version | effective_date | changelog |
|---------|----------------|-----------|
| (Phase 7 で初版を記録) | | |
