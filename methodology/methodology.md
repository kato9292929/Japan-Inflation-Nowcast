# Methodology — Japan Inflation Nowcast

> **これは独立系のナウキャスト（速報）です。総務省の公式統計ではなく、それと同一でも
> ありません。** 食料 + 住居の 2 コンポーネントのみで、CPI バスケットの一部
> （約 47.13%）しかカバーしません。すべての合成値に `coverage_pct`（必ず
> 100 未満）を併記します。透明性が唯一最大の差別化であり、本書は第三者が再現できる
> 粒度で公開します（盛りません）。

- 生成元: `config/baskets.yaml`
- 基準期 (base_date): `2025-01-01`
- ウェイト出典 (weights_source): MIC CPI (placeholder weights — 運用者が基準年ウェイトに更新する)
- methodology_version: `v1`

## インデックスコード

| code | 内容 |
|------|------|
| `JP-INFL-NOWCAST` | 合成（部分カバー, `composite_partial`） |
| `JP-INFL-FOOD` | 食料コンポーネント |
| `JP-INFL-HOUSING` | 住居コンポーネント（募集賃料ベース） |

## 住居 JP-INFL-HOUSING（ヘドニック主系列）

直近 28 日ローリング窓の active 募集で次の OLS を推定する:

```
ln(rent_total) ~ log_area + C(ward) + C(age_band) + C(walk_band)
                 + floor + C(structure) + C(madori)
```

推定面で代表バスケット（ward × madori の固定スペック + ストックウェイト、下表）の
賃料を予測し、基準期予測値に対する比 × 100 を指数とする（構成バイアス耐性: 価格一律
+5% → 指数 +5%、構成のみ変化 → 不変）。

- **クロスチェック（ラスパイレス）**: ward × madori × age_band × walk_band で層化し、
  各層の中央 ¥/m² を基準期固定ウェイトで加重。主系列との乖離を `divergence_pct` で監視。
- **フロー**: 新規掲載（first_seen == 当日）の中央 ¥/m²。先行シグナル。
- **限界**: 募集賃料ベースであり、帰属家賃の厳密推計はしない。

代表ユニット数: 3（`config/baskets.yaml` の `housing.representative_units`）。

## 食料 JP-INFL-FOOD（Jevons + 上位ラスパイレス）

- **基礎集計（elementary, Jevons）**: 中分類ごとに、両期に揃う同一 `sku_key` の価格相対
  （当期 unit_price / 基準期 unit_price）の幾何平均。`unit_price` はパックサイズ・単位差を
  吸収した正準単価（質量 ¥/100g・容量 ¥/100ml・個数 ¥/個）。
- **上位集計（ラスパイレス）**: 中分類を CPI 食料ウェイト（下表）で加重。
- **特売**: `incl_promo` / `excl_promo` の 2 系列。基調は `incl_promo`。
- **SKU 入替**: 両期 matched-SKU のみで相対を取り、消失/新規はチェーンで連続化。

### 食料 中分類ウェイト

| 中分類 | weight |
|--------|--------|
| 穀類 | 1 |
| 魚介類 | 1 |
| 肉類 | 1 |
| 乳卵類 | 1 |
| 野菜・海藻 | 1 |
| 果物 | 1 |
| 油脂・調味料 | 1 |
| 菓子類 | 1 |
| 調理食品 | 1 |
| 飲料 | 1 |
| 豆腐・大豆製品 | 1 |

## 合成 JP-INFL-NOWCAST + coverage

FOOD と HOUSING を、含まれるコンポーネント内で**正規化**した CPI 費目ウェイトで加重平均する:

```
value = Σ(component_value × weight) / Σ(weight)
```

`coverage_pct` は**正規化しない**。CPI 総ウェイト 10000 に対する構成ウェイト
合計の割合で、「CPI バスケットのどれだけをカバーしているか」を示す正直な値であり、
**必ず 100 未満**である:

```
coverage_pct = Σ(weights) / 10000 × 100 = 47.13%
```

### 合成ウェイト（CPI 10000 分比）

| code | weight | CPI 比 |
|------|--------|--------|
| `JP-INFL-FOOD` | 2626 | 26.26% |
| `JP-INFL-HOUSING` | 2087 | 20.87% |

## 共通

- 平滑化 7 日 / 28 日、YoY / MoM / WoW、観測件数 n を併記。
- すべての値に `base_date` と `methodology_version` を紐付ける。

## 既知の限界

- 部分カバー（約 47.13%）。食料・住居以外は未カバー。
- 住居は募集賃料ベース（帰属家賃ではない）。
- スクレイピング対象・法令遵守は運用者責任（生データは非再配布、派生集計のみ公開）。
- ウェイトは基準年依存。リベース時に methodology_version を更新する。

## バージョン履歴

| version | effective_date | changelog |
|---------|----------------|-----------|
| `v1` | 2025-01-01 | 初版（食料 + 住居の部分カバー合成）。 |
