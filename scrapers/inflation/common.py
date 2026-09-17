"""共通フォーマットと厳密な値検証。欠測をゼロに変換しない。"""

from __future__ import annotations

import math
import re
from datetime import UTC, datetime

import httpx

SOURCES = {
    "jp": ("総務省 消費者物価指数", "https://www.stat.go.jp/data/cpi/"),
    "kr": ("KOSTAT / KOSIS", "https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1J22003"),
    "sg": ("SingStat", "https://tablebuilder.singstat.gov.sg/table/TS/M213751"),
}


class InflationError(ValueError):
    """想定外の応答・設定・欠測。公開値への暗黙フォールバックは禁止。"""


def get_json(client: httpx.Client, url: str, params: dict | None = None):
    try:
        response = client.get(url, params=params)
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError):
        # 例外のURLにはキーが含まれるため、ログ・例外チェーンへ出さない。
        raise InflationError("公的APIの通信またはJSON応答に失敗しました") from None


def number(value) -> float:
    if isinstance(value, bool) or value is None:
        raise InflationError("数値が未取得です")
    try:
        result = float(str(value).replace(",", ""))
    except (ValueError, TypeError):
        raise InflationError("非数値または欠測記号を検出しました") from None
    if not math.isfinite(result):
        raise InflationError("有限数ではありません")
    return result


def month(value: str) -> str:
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", value):
        raise InflationError("対象月の形式が不正です")
    return value


def one(rows: list[dict], predicate) -> dict:
    found = [row for row in rows if predicate(row)]
    if len(found) != 1:
        raise InflationError("系列の一致件数が1件ではありません")
    return found[0]


def empty_record(country: str) -> dict:
    source, url = SOURCES[country]
    return {
        "country": country,
        "source": source,
        "source_url": url,
        "as_of": None,
        "released_at": None,
        "fetched_at": None,
        "frequency": "monthly",
        "cpi_yoy": None,
        "cpi_index": {"value": None, "base_year": None, "base_value": 100},
        "food_yoy": None,
        "units": {"cpi_yoy": "percent", "cpi_index": "index", "food_yoy": "percent"},
        "metric_status": {
            "cpi_yoy": "not_fetched",
            "cpi_index": "not_fetched",
            "food_yoy": "not_supported" if country == "kr" else "not_fetched",
        },
        "yoy_method": "index_ratio" if country == "kr" else "published",
        "status": "not_fetched",
        "stale": True,
        "stale_reasons": ["not_fetched"],
        "last_attempt_at": None,
        "last_error": None,
    }


def record(country: str, as_of: str, index, base_year: int, yoy, food=None) -> dict:
    result = empty_record(country)
    index = number(index)
    if index <= 0 or not 1900 <= base_year <= 2100:
        raise InflationError("指数または基準年が不正です")
    result.update(
        as_of=month(as_of),
        fetched_at=datetime.now(UTC).isoformat(),
        cpi_yoy=number(yoy),
        cpi_index={"value": index, "base_year": base_year, "base_value": 100},
        food_yoy=number(food) if food is not None else None,
        status="ok",
        stale=False,
        stale_reasons=[],
    )
    result["metric_status"] = {
        "cpi_index": "available",
        "cpi_yoy": "available",
        "food_yoy": "available" if food is not None else "not_supported",
    }
    return result
