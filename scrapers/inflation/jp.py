"""e-Stat API 3.0。表・系列はメタ情報で照合してから取得する。"""

from __future__ import annotations

import os
import re
from datetime import UTC, datetime

import httpx

from .common import InflationError, get_json, month, one, record

BASE_URL = "https://api.e-stat.go.jp/rest/3.0/app/json"
TABLE_ID = "0004052037"  # 公式DBで確認した2025年基準CPI


def as_list(value):
    return value if isinstance(value, list) else [value]


def checked(payload: dict, root: str, body: str) -> dict:
    response = payload[root]
    if str(response["RESULT"]["STATUS"]) != "0":
        raise InflationError("e-Statがエラーを返しました")
    return response[body]


def fetch(client: httpx.Client, env=os.environ) -> dict:
    key = env.get("ESTAT_APP_ID")
    if not key:
        raise InflationError("ESTAT_APP_IDが未設定です")
    params = {"appId": key, "statsDataId": TABLE_ID, "lang": "J"}
    meta = checked(
        get_json(client, f"{BASE_URL}/getMetaInfo", params), "GET_META_INFO", "METADATA_INF"
    )
    title = meta["TABLE_INF"]["TITLE"]
    title = title["$"] if isinstance(title, dict) else title
    if "消費者物価指数" not in title or "2025年基準" not in title:
        raise InflationError("日本CPIの表または基準年が変わりました")
    classes = {obj["@id"]: as_list(obj["CLASS"]) for obj in as_list(meta["CLASS_INF"]["CLASS_OBJ"])}
    index_tab = one(classes["tab"], lambda r: r["@name"] == "指数")["@code"]
    yoy_tab = one(classes["tab"], lambda r: r["@name"] == "前年同月比")["@code"]
    all_items = one(classes["cat01"], lambda r: r["@name"] == "総合")["@code"]
    food = one(classes["cat01"], lambda r: r["@name"] == "食料")["@code"]
    area = one(classes["area"], lambda r: r["@name"] == "全国")["@code"]
    times = {}
    for entry in classes["time"]:
        match = re.fullmatch(r"(\d{4})年\s*(\d{1,2})月", entry["@name"])
        if match:
            period = month(f"{match[1]}-{int(match[2]):02d}")
            if period <= datetime.now(UTC).strftime("%Y-%m"):
                times[entry["@code"]] = period
    selected = sorted(times, key=times.get)[-18:]
    if not selected:
        raise InflationError("e-Statの月次時間軸が見つかりません")
    params.update(
        cdTab=f"{index_tab},{yoy_tab}",
        cdCat01=f"{all_items},{food}",
        cdArea=area,
        cdTime=",".join(selected),
        metaGetFlg="Y",
        cntGetFlg="N",
        limit="10000",
    )
    data = checked(
        get_json(client, f"{BASE_URL}/getStatsData", params), "GET_STATS_DATA", "STATISTICAL_DATA"
    )
    if data["RESULT_INF"].get("NEXT_KEY"):
        raise InflationError("e-Stat応答が取得上限を超えました")
    rows = as_list(data["DATA_INF"]["VALUE"])
    if not rows or any(r["@area"] != area or r["@time"] not in selected for r in rows):
        raise InflationError("e-Stat応答の地域・対象月が不正です")
    latest = max(times[r["@time"]] for r in rows)

    def value(tab, category):
        row = one(
            rows,
            lambda r: times[r["@time"]] == latest and r["@tab"] == tab and r["@cat01"] == category,
        )
        return row["$"]

    return record(
        "jp",
        latest,
        value(index_tab, all_items),
        2025,
        value(yoy_tab, all_items),
        value(yoy_tab, food),
    )
