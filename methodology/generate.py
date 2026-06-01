"""methodology.md 生成 + methodology_versions 記録（§6, §6-4）。

config（baskets.yaml の weights / 代表ユニット / categories / composite_weights /
base_date）から、第三者が再現できる粒度の方法論ドキュメントを生成する。

§0 遵守: 「公式 CPI」「CPI そのもの」と誤認させる表記を入れない。部分カバーの
ナウキャスト（速報）であることを明示し、coverage は必ず 100 未満であると記す。
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import yaml

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
BASKETS_PATH = CONFIG_DIR / "baskets.yaml"
METHODOLOGY_PATH = Path(__file__).resolve().parent / "methodology.md"

CPI_TOTAL_WEIGHT = 10000.0
CURRENT_VERSION = "v1"


def _load_config() -> dict[str, Any]:
    if not BASKETS_PATH.exists():
        return {}
    return yaml.safe_load(BASKETS_PATH.read_text(encoding="utf-8")) or {}


def build_methodology_md(config: dict[str, Any] | None = None) -> str:
    """config から methodology.md 本文（Markdown 文字列）を生成する。"""
    cfg = config if config is not None else _load_config()
    composite_weights = cfg.get("composite_weights") or {}
    food = cfg.get("food") or {}
    housing = cfg.get("housing") or {}
    base_date = cfg.get("base_date", "—")
    weights_source = cfg.get("weights_source", "総務省 CPI 基準年（運用者が更新）")

    w_total = sum(float(v) for v in composite_weights.values())
    coverage = w_total / CPI_TOTAL_WEIGHT * 100.0

    food_cats = food.get("categories") or []
    rep_units = housing.get("representative_units") or []
    window = housing.get("rolling_window_days", 28)
    default_promo = food.get("default_promo_mode", "excl_promo")

    weight_rows = "\n".join(
        f"| `{code}` | {float(w):.0f} | {float(w) / CPI_TOTAL_WEIGHT * 100:.2f}% |"
        for code, w in composite_weights.items()
    )
    cat_rows = "\n".join(
        f"| {c.get('name')} | {float(c.get('weight', 1)):.0f} |" for c in food_cats
    )

    return f"""# Methodology — Japan Inflation Nowcast

> **これは独立系のナウキャスト（速報）です。総務省の公式統計ではなく、それと同一でも
> ありません。** 食料 + 住居の 2 コンポーネントのみで、CPI バスケットの一部
> （約 {coverage:.2f}%）しかカバーしません。すべての合成値に `coverage_pct`（必ず
> 100 未満）を併記します。透明性が唯一最大の差別化であり、本書は第三者が再現できる
> 粒度で公開します（盛りません）。

- 生成元: `config/baskets.yaml`
- 基準期 (base_date): `{base_date}`
- ウェイト出典 (weights_source): {weights_source}
- methodology_version: `{CURRENT_VERSION}`

## インデックスコード

| code | 内容 |
|------|------|
| `JP-INFL-NOWCAST` | 合成（部分カバー, `composite_partial`） |
| `JP-INFL-FOOD` | 食料コンポーネント |
| `JP-INFL-HOUSING` | 住居コンポーネント（募集賃料ベース） |

## 住居 JP-INFL-HOUSING（ヘドニック主系列）

直近 {window} 日ローリング窓の active 募集で次の OLS を推定する:

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

代表ユニット数: {len(rep_units)}（`config/baskets.yaml` の `housing.representative_units`）。

## 食料 JP-INFL-FOOD（Jevons + 上位ラスパイレス）

- **基礎集計（elementary, Jevons）**: 中分類ごとに、両期に揃う同一 `sku_key` の価格相対
  （当期 unit_price / 基準期 unit_price）の幾何平均。`unit_price` はパックサイズ・単位差を
  吸収した正準単価（質量 ¥/100g・容量 ¥/100ml・個数 ¥/個）。
- **上位集計（ラスパイレス）**: 中分類を CPI 食料ウェイト（下表）で加重。
- **特売**: `incl_promo` / `excl_promo` の 2 系列。基調は `{default_promo}`。
- **SKU 入替**: 両期 matched-SKU のみで相対を取り、消失/新規はチェーンで連続化。

### 食料 中分類ウェイト

| 中分類 | weight |
|--------|--------|
{cat_rows}

## 合成 JP-INFL-NOWCAST + coverage

FOOD と HOUSING を、含まれるコンポーネント内で**正規化**した CPI 費目ウェイトで加重平均する:

```
value = Σ(component_value × weight) / Σ(weight)
```

`coverage_pct` は**正規化しない**。CPI 総ウェイト {CPI_TOTAL_WEIGHT:.0f} に対する構成ウェイト
合計の割合で、「CPI バスケットのどれだけをカバーしているか」を示す正直な値であり、
**必ず 100 未満**である:

```
coverage_pct = Σ(weights) / {CPI_TOTAL_WEIGHT:.0f} × 100 = {coverage:.2f}%
```

### 合成ウェイト（CPI 10000 分比）

| code | weight | CPI 比 |
|------|--------|--------|
{weight_rows}

## 共通

- 平滑化 7 日 / 28 日、YoY / MoM / WoW、観測件数 n を併記。
- すべての値に `base_date` と `methodology_version` を紐付ける。

## 既知の限界

- 部分カバー（約 {coverage:.2f}%）。食料・住居以外は未カバー。
- 住居は募集賃料ベース（帰属家賃ではない）。
- スクレイピング対象・法令遵守は運用者責任（生データは非再配布、派生集計のみ公開）。
- ウェイトは基準年依存。リベース時に methodology_version を更新する。

## バージョン履歴

| version | effective_date | changelog |
|---------|----------------|-----------|
| `{CURRENT_VERSION}` | {base_date} | 初版（食料 + 住居の部分カバー合成）。 |
"""


def write_methodology(path: Path = METHODOLOGY_PATH, config: dict[str, Any] | None = None) -> str:
    """methodology.md を生成して書き出す。生成した本文を返す。"""
    content = build_methodology_md(config)
    path.write_text(content, encoding="utf-8")
    return content


def record_version(
    session: Any,
    *,
    version: str = CURRENT_VERSION,
    effective_date: date | None = None,
    formula_notes: str | None = None,
    weights_source: str | None = None,
    changelog: str | None = None,
) -> None:
    """methodology_versions に version を冪等記録する（§5, §6-4）。"""
    from sqlmodel import select

    from storage.models import MethodologyVersion

    cfg = _load_config()
    if effective_date is None:
        bd = cfg.get("base_date")
        effective_date = date.fromisoformat(bd) if isinstance(bd, str) else (bd or date.today())
    if weights_source is None:
        weights_source = cfg.get("weights_source")

    existing = session.exec(
        select(MethodologyVersion).where(MethodologyVersion.version == version)
    ).first()
    if existing is None:
        session.add(
            MethodologyVersion(
                version=version,
                effective_date=effective_date,
                formula_notes=formula_notes or "hedonic + laspeyres + Jevons; composite_partial",
                weights_source=weights_source,
                changelog=changelog or "初版（食料 + 住居の部分カバー合成）。",
            )
        )
    else:
        existing.effective_date = effective_date
        existing.weights_source = weights_source
        if formula_notes:
            existing.formula_notes = formula_notes
        if changelog:
            existing.changelog = changelog
        session.add(existing)
    session.commit()
