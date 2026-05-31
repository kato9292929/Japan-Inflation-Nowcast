"""住居 ETL（§5, §6-1）。生 listings -> listings_clean。

責務:
- 住所/区/駅の正規化（config/normalize/*.yaml）。
- dedup（同一 listing_id の統合）。
- ライフサイクル更新（first_seen / last_seen / is_active）。
- ヘドニック用特徴量（log_area, age_band, walk_band, rent_per_m2）。

すべて冪等（同日再実行で二重計上しない, §3）。
"""

from __future__ import annotations

import math
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from sqlmodel import select

from storage.db import get_session
from storage.models import ListingClean, ListingRaw

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
NORMALIZE_DIR = CONFIG_DIR / "normalize"
BASKETS_PATH = CONFIG_DIR / "baskets.yaml"

# winsorize 既定（config に無い場合, §6-1）。
_DEFAULT_WINSOR_MIN = 1000.0
_DEFAULT_WINSOR_MAX = 50000.0
# 構造の正規化マップ（代表的な表記ゆれ -> 正規コード）。
_STRUCTURE_MAP = {
    "RC": "RC",
    "ＲＣ": "RC",
    "鉄筋コンクリート": "RC",
    "SRC": "SRC",
    "ＳＲＣ": "SRC",
    "鉄骨鉄筋コンクリート": "SRC",
    "鉄骨": "S",
    "S": "S",
    "木造": "W",
    "木": "W",
}

# raw -> clean に持ち込むフィールド。
_CARRY_FIELDS = (
    "ward",
    "station",
    "walk_min",
    "rent_total",
    "mgmt_fee",
    "area_m2",
    "madori",
    "build_year",
    "floor",
    "structure",
    "deposit",
    "key_money",
)


# --------------------------------------------------------------------------- #
# 設定ロード
# --------------------------------------------------------------------------- #
@lru_cache
def _load_yaml(path_str: str) -> dict[str, Any]:
    path = Path(path_str)
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _ward_aliases() -> dict[str, str]:
    return _load_yaml(str(NORMALIZE_DIR / "ward.yaml")).get("aliases") or {}


def _station_aliases() -> dict[str, str]:
    return _load_yaml(str(NORMALIZE_DIR / "station.yaml")).get("aliases") or {}


def _address_replacements() -> dict[str, str]:
    return _load_yaml(str(NORMALIZE_DIR / "address.yaml")).get("replacements") or {}


def _housing_config() -> dict[str, Any]:
    return _load_yaml(str(BASKETS_PATH)).get("housing") or {}


def _winsor_bounds() -> tuple[float, float]:
    cfg = _housing_config().get("winsor_rent_per_m2") or {}
    lo = float(cfg.get("min", _DEFAULT_WINSOR_MIN))
    hi = float(cfg.get("max", _DEFAULT_WINSOR_MAX))
    return lo, hi


def _age_bands() -> list[float]:
    return [float(x) for x in (_housing_config().get("age_bands") or [5, 10, 20, 30])]


def _walk_bands() -> list[float]:
    return [float(x) for x in (_housing_config().get("walk_bands") or [5, 10, 15])]


# --------------------------------------------------------------------------- #
# 数値ユーティリティ
# --------------------------------------------------------------------------- #
def _to_float(value: Any) -> float | None:
    if value is None:
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


def _to_int(value: Any) -> int | None:
    f = _to_float(value)
    return int(f) if f is not None else None


def _bucket(value: float, bounds: list[float]) -> int:
    """value を昇順境界 bounds でバケット化したコード（0..len(bounds)）。"""
    for i, b in enumerate(bounds):
        if value < b:
            return i
    return len(bounds)


# --------------------------------------------------------------------------- #
# 1) 生 upsert + ライフサイクル
# --------------------------------------------------------------------------- #
def _coerce_raw(record: dict[str, Any]) -> dict[str, Any]:
    """parse 出力を ListingRaw のカラム型に最小整形する（正規化はしない）。"""
    return {
        "ward": record.get("ward"),
        "address_norm": record.get("address"),  # raw 段階では未正規化の住所をそのまま保持
        "station": record.get("station"),
        "walk_min": _to_int(record.get("walk_min")),
        "rent_total": _to_float(record.get("rent_total")),
        "mgmt_fee": _to_float(record.get("mgmt_fee")),
        "area_m2": _to_float(record.get("area_m2")),
        "madori": record.get("madori"),
        "build_year": _to_int(record.get("build_year")),
        "floor": _to_int(record.get("floor")),
        "structure": record.get("structure"),
        "deposit": _to_float(record.get("deposit")),
        "key_money": _to_float(record.get("key_money")),
        "raw_payload": record.get("raw_payload"),
    }


def upsert_raw(records: list[dict[str, Any]], *, scrape_date: date) -> int:
    """生レコードを listings_raw に冪等 upsert し、ライフサイクルを更新する。

    - 冪等キー = (source, listing_id)。
    - 新規: first_seen = last_seen = scrape_date, is_active=True。
    - 既存: last_seen=scrape_date, is_active=True、フィールド更新（first_seen は保持）。
    - 今回バッチに無い既存 active 行（同一 source）は is_active=False に倒す（市場退出）。

    Returns: 取り込んだ行数（= records 件数）。
    """
    seen_keys: set[tuple[str, str]] = set()
    sources_in_batch: set[str] = set()
    count = 0

    with get_session() as session:
        for rec in records:
            source = rec["source"]
            listing_id = rec["listing_id"]
            seen_keys.add((source, listing_id))
            sources_in_batch.add(source)
            fields = _coerce_raw(rec)

            existing = session.exec(
                select(ListingRaw).where(
                    ListingRaw.source == source,
                    ListingRaw.listing_id == listing_id,
                )
            ).first()

            if existing is None:
                row = ListingRaw(
                    listing_id=listing_id,
                    source=source,
                    scrape_date=scrape_date,
                    first_seen=scrape_date,
                    last_seen=scrape_date,
                    is_active=True,
                    **fields,
                )
                session.add(row)
            else:
                existing.scrape_date = scrape_date
                existing.last_seen = scrape_date
                existing.is_active = True  # first_seen は保持
                for key, value in fields.items():
                    setattr(existing, key, value)
                session.add(existing)
            count += 1

        # 市場退出: 今回バッチに現れなかった既存 active 行を is_active=False。
        for source in sources_in_batch:
            actives = session.exec(
                select(ListingRaw).where(
                    ListingRaw.source == source,
                    ListingRaw.is_active.is_(True),
                )
            ).all()
            for row in actives:
                if (row.source, row.listing_id) not in seen_keys:
                    row.is_active = False
                    session.add(row)

        session.commit()

    return count


# --------------------------------------------------------------------------- #
# 2) 正規化
# --------------------------------------------------------------------------- #
def _normalize_address(address: str | None) -> str | None:
    if not address:
        return None
    out = address
    for src, dst in _address_replacements().items():
        out = out.replace(src, dst)
    return out.strip() or None


def _normalize_structure(structure: str | None) -> str | None:
    if not structure:
        return None
    return _STRUCTURE_MAP.get(structure.strip(), structure.strip())


def _normalize_madori(madori: str | None) -> str | None:
    if not madori:
        return None
    return madori.strip().upper().replace(" ", "").replace("　", "")


def normalize_listing(record: dict[str, Any]) -> dict[str, Any]:
    """1 物件を正規化（ward/station/address、数値化、カテゴリ正規化、winsorize）。

    入力は raw 行相当の dict。出力は clean に書ける正規化済み dict。
    """
    out = dict(record)

    ward = record.get("ward")
    out["ward"] = _ward_aliases().get(ward, ward) if ward else None

    station = record.get("station")
    out["station"] = _station_aliases().get(station, station) if station else None

    # raw では address を address_norm にそのまま入れている。ここで正規化する。
    out["address_norm"] = _normalize_address(record.get("address_norm") or record.get("address"))

    out["structure"] = _normalize_structure(record.get("structure"))
    out["madori"] = _normalize_madori(record.get("madori"))

    rent_total = _to_float(record.get("rent_total"))
    area_m2 = _to_float(record.get("area_m2"))
    out["rent_total"] = rent_total
    out["mgmt_fee"] = _to_float(record.get("mgmt_fee"))
    out["area_m2"] = area_m2
    out["walk_min"] = _to_int(record.get("walk_min"))
    out["build_year"] = _to_int(record.get("build_year"))
    out["floor"] = _to_int(record.get("floor"))
    out["deposit"] = _to_float(record.get("deposit"))
    out["key_money"] = _to_float(record.get("key_money"))

    # ¥/m^2 異常値 winsorize（rent_total を境界 × 面積でクリップ）。
    if rent_total and area_m2 and area_m2 > 0:
        lo, hi = _winsor_bounds()
        rpm = rent_total / area_m2
        if rpm < lo:
            out["rent_total"] = lo * area_m2
        elif rpm > hi:
            out["rent_total"] = hi * area_m2

    return out


# --------------------------------------------------------------------------- #
# 3) 特徴量
# --------------------------------------------------------------------------- #
def build_features(record: dict[str, Any], *, as_of_year: int | None = None) -> dict[str, Any]:
    """ヘドニック特徴量（log_area, age_band, walk_band, rent_per_m2）を付与する。

    None / 0 除算をガードする。as_of_year を渡せば築年帯計算を決定的にできる（テスト用）。
    """
    out = dict(record)
    ref_year = as_of_year if as_of_year is not None else date.today().year

    area_m2 = _to_float(record.get("area_m2"))
    rent_total = _to_float(record.get("rent_total"))
    walk_min = _to_int(record.get("walk_min"))
    build_year = _to_int(record.get("build_year"))

    out["log_area"] = math.log(area_m2) if area_m2 and area_m2 > 0 else None
    out["rent_per_m2"] = (
        rent_total / area_m2 if rent_total is not None and area_m2 and area_m2 > 0 else None
    )
    out["age_band"] = (
        _bucket(float(max(ref_year - build_year, 0)), _age_bands())
        if build_year is not None
        else None
    )
    out["walk_band"] = (
        _bucket(float(walk_min), _walk_bands()) if walk_min is not None else None
    )
    return out


# --------------------------------------------------------------------------- #
# 4) パイプライン: raw -> clean（冪等）
# --------------------------------------------------------------------------- #
def _row_to_dict(row: ListingRaw) -> dict[str, Any]:
    return {
        "source": row.source,
        "listing_id": row.listing_id,
        "is_active": row.is_active,
        "first_seen": row.first_seen,
        "last_seen": row.last_seen,
        "ward": row.ward,
        "address_norm": row.address_norm,
        "station": row.station,
        "walk_min": row.walk_min,
        "rent_total": row.rent_total,
        "mgmt_fee": row.mgmt_fee,
        "area_m2": row.area_m2,
        "madori": row.madori,
        "build_year": row.build_year,
        "floor": row.floor,
        "structure": row.structure,
        "deposit": row.deposit,
        "key_money": row.key_money,
    }


def run(*, scrape_date: date, as_of_year: int | None = None) -> int:
    """listings_raw -> listings_clean を冪等に再構築する。

    raw を読み、(source, listing_id) で dedup（同一は最新 scrape_date を採用）、
    normalize -> build_features して clean へ upsert（同キーは更新）。
    同 scrape_date 再実行でも二重化しない。

    Returns: 生成/更新した clean 行数。
    """
    count = 0
    with get_session() as session:
        raw_rows = session.exec(select(ListingRaw)).all()

        # (source, listing_id) で最新 scrape_date を採用して dedup。
        latest: dict[tuple[str, str], ListingRaw] = {}
        for row in raw_rows:
            key = (row.source, row.listing_id)
            prev = latest.get(key)
            if prev is None or row.scrape_date >= prev.scrape_date:
                latest[key] = row

        for (source, listing_id), row in latest.items():
            normalized = normalize_listing(_row_to_dict(row))
            featured = build_features(normalized, as_of_year=as_of_year)

            existing = session.exec(
                select(ListingClean).where(
                    ListingClean.source == source,
                    ListingClean.listing_id == listing_id,
                )
            ).first()

            payload = {
                "scrape_date": scrape_date,
                "first_seen": row.first_seen,
                "last_seen": row.last_seen,
                "is_active": row.is_active,
                "address_norm": featured.get("address_norm"),
                "log_area": featured.get("log_area"),
                "age_band": featured.get("age_band"),
                "walk_band": featured.get("walk_band"),
                "rent_per_m2": featured.get("rent_per_m2"),
            }
            for f in _CARRY_FIELDS:
                payload[f] = featured.get(f)

            if existing is None:
                session.add(
                    ListingClean(source=source, listing_id=listing_id, **payload)
                )
            else:
                for key, value in payload.items():
                    setattr(existing, key, value)
                session.add(existing)
            count += 1

        session.commit()

    return count
