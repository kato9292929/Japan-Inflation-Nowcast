"""食料 ETL（§5, §6-2）。生 food -> food_clean。

責務:
- SKU 名寄せ（同一商品を時系列で追跡できる sku_key を付与）。
- 単価正規化（unit_price = price / unit_size を正準単位に換算）。
- ライフサイクル更新（first_seen / last_seen / is_active）。
- CPI 食料中分類（category）の保持。

肝（Phase 4 Jevons の前提, §6-2）:
- sku_key は item_id（source 内 ID）が変わっても同一商品を同一キーに落とす時系列同定キー。
- unit_price はパックサイズ・単位表現の差を吸収した正準単価（質量¥/100g・容量¥/100ml・個数¥/個）。

すべて冪等（§3）。
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from sqlmodel import select

from storage.db import get_session
from storage.models import FoodClean, FoodRaw

# 正準単位系: family -> (基準単位あたりの表示量, 100 単位刻みか)。
# 質量は g、容量は ml を基準に「¥/100基準」、個数は「¥/個」。
_MASS_TO_G = {"g": 1.0, "ｇ": 1.0, "gram": 1.0, "grams": 1.0, "グラム": 1.0,
              "kg": 1000.0, "㎏": 1000.0, "キロ": 1000.0, "キログラム": 1000.0}
_VOL_TO_ML = {"ml": 1.0, "ｍｌ": 1.0, "cc": 1.0, "ミリ": 1.0, "ミリリットル": 1.0,
              "l": 1000.0, "ℓ": 1000.0, "リットル": 1000.0, "litre": 1000.0, "liter": 1000.0}
_COUNT_UNITS = {"個", "こ", "枚", "本", "玉", "パック", "pack", "pcs", "pc", "袋", "缶", "本入",
                "束", "房", "切", "株", "把", "尾"}

# clean に持ち込む FoodRaw 由来フィールド。
_CARRY_FIELDS = (
    "category",
    "product_name",
    "brand",
    "unit",
    "unit_size",
    "price",
    "is_promo",
    "in_stock",
)


# --------------------------------------------------------------------------- #
# 数値・文字列ユーティリティ
# --------------------------------------------------------------------------- #
def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    cleaned = str(value).replace(",", "").replace("¥", "").replace("円", "").strip()
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _to_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    token = str(value).strip().lower()
    if token in {"true", "1", "yes", "y"}:
        return True
    if token in {"false", "0", "no", "n"}:
        return False
    return default


def _norm_token(text: Any) -> str:
    """名寄せ用トークン正規化: 小文字化・空白除去・記号圧縮。"""
    if text is None:
        return ""
    s = str(text).strip().lower()
    s = s.replace("　", "")  # 全角空白
    s = re.sub(r"\s+", "", s)
    return s


def _unit_family(unit: Any) -> str | None:
    """unit を正準ファミリ（'mass' / 'volume' / 'count'）へ分類。不明は None。"""
    token = _norm_token(unit)
    if not token:
        return None
    if token in _MASS_TO_G:
        return "mass"
    if token in _VOL_TO_ML:
        return "volume"
    if token in _COUNT_UNITS:
        return "count"
    return None


def _norm_unit_key(unit: Any) -> str:
    """sku_key 用の正規化 unit。同一ファミリ（g/kg 等）は同じトークンに畳む。"""
    family = _unit_family(unit)
    if family is not None:
        return family
    return _norm_token(unit)


# --------------------------------------------------------------------------- #
# 1) SKU 名寄せ（時系列同定キー）
# --------------------------------------------------------------------------- #
def resolve_sku_key(record: dict[str, Any]) -> str:
    """同一商品を時系列で追う連続キー = normalize(brand)+name+unit（§6-2）。

    item_id は source 内 ID なので使わない。表記/パック単位の差を畳んで同定する。
    """
    brand = _norm_token(record.get("brand"))
    name = _norm_token(record.get("product_name"))
    unit = _norm_unit_key(record.get("unit"))
    return "|".join([brand, name, unit])


# --------------------------------------------------------------------------- #
# 2) 単価正規化（パックサイズ・単位差を吸収）
# --------------------------------------------------------------------------- #
def normalize_unit_price(record: dict[str, Any]) -> float | None:
    """price/unit_size をカテゴリ内比較可能な正準単価に正規化（§6-2）。

    - 質量: ¥/100g、容量: ¥/100ml、個数: ¥/個。
    - unit を正準系へ換算（kg→g, l→ml）。
    - unit_size 欠損/0、price 欠損、未知単位はガードして None。
    """
    price = _to_float(record.get("price"))
    size = _to_float(record.get("unit_size"))
    if price is None or size is None or size <= 0:
        return None

    family = _unit_family(record.get("unit"))
    token = _norm_token(record.get("unit"))
    if family == "mass":
        grams = size * _MASS_TO_G[token]
        return price / grams * 100.0
    if family == "volume":
        ml = size * _VOL_TO_ML[token]
        return price / ml * 100.0
    if family == "count":
        return price / size
    return None  # 未知単位は正準化できない


# --------------------------------------------------------------------------- #
# 3) 生 upsert + ライフサイクル
# --------------------------------------------------------------------------- #
def _coerce_raw(record: dict[str, Any]) -> dict[str, Any]:
    """parse 出力を FoodRaw のカラム型に最小整形する（名寄せ/正準化はしない）。"""
    return {
        "category": record.get("category"),
        "product_name": record.get("product_name"),
        "brand": record.get("brand"),
        "unit": record.get("unit"),
        "unit_size": _to_float(record.get("unit_size")),
        "price": _to_float(record.get("price")),
        "is_promo": _to_bool(record.get("is_promo"), default=False),
        "in_stock": _to_bool(record.get("in_stock"), default=True),
        "raw_payload": record.get("raw_payload"),
    }


def upsert_raw(records: list[dict[str, Any]], *, scrape_date: date) -> int:
    """生レコードを food_raw に冪等 upsert し、ライフサイクルを更新する。

    - 冪等キー = (source, item_id)。
    - 新規: first_seen = last_seen = scrape_date, is_active=True。
    - 既存: last_seen=scrape_date, is_active=True、フィールド更新（first_seen 保持）。
    - 今回バッチに無い既存 active 行（同一 source）は is_active=False（棚落ち/取扱終了）。

    Returns: 取り込んだ行数（= records 件数）。
    """
    seen_keys: set[tuple[str, str]] = set()
    sources_in_batch: set[str] = set()
    count = 0

    with get_session() as session:
        for rec in records:
            source = rec["source"]
            item_id = rec["item_id"]
            seen_keys.add((source, item_id))
            sources_in_batch.add(source)
            fields = _coerce_raw(rec)

            existing = session.exec(
                select(FoodRaw).where(
                    FoodRaw.source == source,
                    FoodRaw.item_id == item_id,
                )
            ).first()

            if existing is None:
                session.add(
                    FoodRaw(
                        item_id=item_id,
                        source=source,
                        scrape_date=scrape_date,
                        first_seen=scrape_date,
                        last_seen=scrape_date,
                        is_active=True,
                        **fields,
                    )
                )
            else:
                existing.scrape_date = scrape_date
                existing.last_seen = scrape_date
                existing.is_active = True  # first_seen は保持
                for key, value in fields.items():
                    setattr(existing, key, value)
                session.add(existing)
            count += 1

        # 棚落ち: 今回バッチに現れなかった既存 active 行を is_active=False。
        for source in sources_in_batch:
            actives = session.exec(
                select(FoodRaw).where(
                    FoodRaw.source == source,
                    FoodRaw.is_active.is_(True),
                )
            ).all()
            for row in actives:
                if (row.source, row.item_id) not in seen_keys:
                    row.is_active = False
                    session.add(row)

        session.commit()

    return count


# --------------------------------------------------------------------------- #
# 4) パイプライン: raw -> clean（冪等）
# --------------------------------------------------------------------------- #
def _row_to_dict(row: FoodRaw) -> dict[str, Any]:
    return {
        "source": row.source,
        "item_id": row.item_id,
        "is_active": row.is_active,
        "first_seen": row.first_seen,
        "last_seen": row.last_seen,
        "category": row.category,
        "product_name": row.product_name,
        "brand": row.brand,
        "unit": row.unit,
        "unit_size": row.unit_size,
        "price": row.price,
        "is_promo": row.is_promo,
        "in_stock": row.in_stock,
    }


def run(*, scrape_date: date) -> int:
    """food_raw -> food_clean を冪等に再構築する。

    raw を読み、(source, item_id) で dedup（同一は最新 scrape_date を採用）、
    resolve_sku_key と normalize_unit_price を付与、category と is_promo を保持して
    clean へ upsert（同キーは更新）。同 scrape_date 再実行でも二重化しない。

    Returns: 生成/更新した clean 行数。
    """
    count = 0
    with get_session() as session:
        raw_rows = session.exec(select(FoodRaw)).all()

        latest: dict[tuple[str, str], FoodRaw] = {}
        for row in raw_rows:
            key = (row.source, row.item_id)
            prev = latest.get(key)
            if prev is None or row.scrape_date >= prev.scrape_date:
                latest[key] = row

        for (source, item_id), row in latest.items():
            rec = _row_to_dict(row)
            sku_key = resolve_sku_key(rec)
            unit_price = normalize_unit_price(rec)

            existing = session.exec(
                select(FoodClean).where(
                    FoodClean.source == source,
                    FoodClean.item_id == item_id,
                )
            ).first()

            payload = {
                "scrape_date": scrape_date,
                "first_seen": row.first_seen,
                "last_seen": row.last_seen,
                "is_active": row.is_active,
                "sku_key": sku_key,
                "unit_price": unit_price,
            }
            for f in _CARRY_FIELDS:
                payload[f] = rec.get(f)

            if existing is None:
                session.add(FoodClean(source=source, item_id=item_id, **payload))
            else:
                for key, value in payload.items():
                    setattr(existing, key, value)
                session.add(existing)
            count += 1

        session.commit()

    return count
