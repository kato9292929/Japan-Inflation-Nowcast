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
from collections import defaultdict
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


def _recompute_lifecycle(session: Any, source: str) -> None:
    """当該 source の全 SKU について first_seen/last_seen/is_active を整合させる。

    - first_seen = SKU の全行の min(scrape_date)、last_seen = max(scrape_date)。
    - is_active = (last_seen == その source の最も新しい scrape_date)。棚落ち SKU は False。
    - 値は SKU 単位の真実として全行に書き戻す（冗長コピー）。
    """
    rows = session.exec(select(FoodRaw).where(FoodRaw.source == source)).all()
    if not rows:
        return
    global_max = max(r.scrape_date for r in rows)
    by_sku: dict[str, list[FoodRaw]] = defaultdict(list)
    for r in rows:
        by_sku[r.item_id].append(r)
    for group in by_sku.values():
        first = min(r.scrape_date for r in group)
        last = max(r.scrape_date for r in group)
        active = last == global_max
        for r in group:
            r.first_seen = first
            r.last_seen = last
            r.is_active = active
            session.add(r)


def upsert_raw(records: list[dict[str, Any]], *, scrape_date: date) -> int:
    """生レコードを food_raw（日次パネル）に冪等 upsert し、ライフサイクルを整合させる。

    - 冪等キー = (source, item_id, scrape_date)。同日同 SKU の再ランは更新（行は増えない）。
    - 既存日付行が無ければ新規 INSERT（過去日の行は保持＝パネル化）。
    - バッチ後、影響 source の全 SKU の first_seen/last_seen/is_active を recompute（棚落ち含む）。

    Returns: 取り込んだ行数（= records 件数）。
    """
    sources_in_batch: set[str] = set()
    count = 0

    with get_session() as session:
        for rec in records:
            source = rec["source"]
            item_id = rec["item_id"]
            sources_in_batch.add(source)
            fields = _coerce_raw(rec)

            existing = session.exec(
                select(FoodRaw).where(
                    FoodRaw.source == source,
                    FoodRaw.item_id == item_id,
                    FoodRaw.scrape_date == scrape_date,
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
                for key, value in fields.items():
                    setattr(existing, key, value)
                session.add(existing)
            count += 1

        for source in sources_in_batch:
            _recompute_lifecycle(session, source)

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
    """food_raw（日次パネル）-> food_clean を冪等に投影する。

    raw の全行（全 scrape_date）を food_clean に 1:1 投影する。各 scrape_date 行を
    独立行として保持し（dedup しない）、resolve_sku_key / normalize_unit_price を付与、
    category・is_promo・ライフサイクル列を raw から継承する。
    clean の冪等キーは (source, item_id, scrape_date)。同日再ランでも二重化しない。

    Returns: 生成/更新した clean 行数。
    """
    count = 0
    with get_session() as session:
        raw_rows = session.exec(select(FoodRaw)).all()

        for row in raw_rows:
            rec = _row_to_dict(row)
            sku_key = resolve_sku_key(rec)
            unit_price = normalize_unit_price(rec)

            existing = session.exec(
                select(FoodClean).where(
                    FoodClean.source == row.source,
                    FoodClean.item_id == row.item_id,
                    FoodClean.scrape_date == row.scrape_date,
                )
            ).first()

            payload = {
                "first_seen": row.first_seen,
                "last_seen": row.last_seen,
                "is_active": row.is_active,
                "sku_key": sku_key,
                "unit_price": unit_price,
            }
            for f in _CARRY_FIELDS:
                payload[f] = rec.get(f)

            if existing is None:
                session.add(
                    FoodClean(
                        source=row.source,
                        item_id=row.item_id,
                        scrape_date=row.scrape_date,
                        **payload,
                    )
                )
            else:
                for key, value in payload.items():
                    setattr(existing, key, value)
                session.add(existing)
            count += 1

        session.commit()

    return count
