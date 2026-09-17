"""KOSIS統計表選択API。全国総合指数から前年比を計算し、計算法を明示する。"""

from __future__ import annotations

import os
import re

import httpx

from .common import InflationError, get_json, month, number, record

URL = "https://kosis.kr/openapi/Param/statisticsParameterData.do"
TABLE_ID = "DT_1J22003"


def fetch(client: httpx.Client, env=os.environ) -> dict:
    key = env.get("KOSIS_API_KEY")
    region = env.get("KOSIS_CPI_REGION_CODE")
    if not key:
        raise InflationError("KOSIS_API_KEYが未設定です")
    if not region:
        raise InflationError(
            "TODO: 公式URL生成画面で全国コードを確認しKOSIS_CPI_REGION_CODEに設定してください"
        )
    rows = get_json(
        client,
        URL,
        {
            "method": "getList",
            "apiKey": key,
            "format": "json",
            "jsonVD": "Y",
            "orgId": "101",
            "tblId": TABLE_ID,
            "objL1": region,
            "itmId": "T",
            "prdSe": "M",
            "newEstPrdCnt": "13",
        },
    )
    if not isinstance(rows, list) or not rows:
        raise InflationError("KOSISがエラーまたは空の応答を返しました")
    values = {}
    base_years = set()
    for row in rows:
        if (
            row["ORG_ID"] != "101"
            or row["TBL_ID"] != TABLE_ID
            or row["PRD_SE"] != "M"
            or row["ITM_ID"] != "T"
            or row["C1"] != region
            or row["C1_NM"] != "전국"
            or any(row.get(f"C{i}") for i in range(2, 9))
            or "소비자물가지수" not in row["TBL_NM"]
        ):
            raise InflationError("KOSISの全国・月次・総合CPIの照合に失敗しました")
        match = re.fullmatch(r"(\d{4})\s*[=＝]\s*100", row["UNIT_NM"])
        if not match:
            raise InflationError("KOSISの指数基準が不明です")
        base_years.add(int(match[1]))
        raw = row["PRD_DE"]
        if not re.fullmatch(r"\d{6}", raw):
            raise InflationError("KOSISの月次時間軸が不正です")
        period = month(f"{raw[:4]}-{raw[4:]}")
        if period in values:
            raise InflationError("KOSISの対象月が重複しています")
        values[period] = number(row["DT"])
    if len(base_years) != 1:
        raise InflationError("異なる基準年の指数を比較できません")
    latest = max(values)
    previous = f"{int(latest[:4]) - 1}{latest[4:]}"
    if previous not in values or values[previous] <= 0:
        raise InflationError("前年同月の指数が未取得です")
    yoy = round((values[latest] / values[previous] - 1) * 100, 6)
    return record("kr", latest, values[latest], base_years.pop(), yoy)
