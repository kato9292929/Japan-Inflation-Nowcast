"""SingStat Table Builder API。公式の指数表と前年同月比表を照合する。"""

from __future__ import annotations

import httpx

from .common import InflationError, get_json, month, one, record

BASE_URL = "https://tablebuilder.singstat.gov.sg/api/table"
INDEX_TABLE = "M213751"
YOY_TABLE = "M213781"
MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()


def parse_month(value: str) -> str:
    parts = value.split()
    if len(parts) != 2 or parts[1] not in MONTHS:
        raise InflationError("SingStatの月次時間軸が不正です")
    return month(f"{parts[0]}-{MONTHS.index(parts[1]) + 1:02d}")


def checked(payload: dict) -> dict:
    if payload["StatusCode"] != 200:
        raise InflationError("SingStatがエラーを返しました")
    return payload["Data"]


def fetch_table(client: httpx.Client, table: str, names: list[str], unit: str) -> tuple:
    meta = checked(get_json(client, f"{BASE_URL}/metadata/{table}"))["records"]
    expected_title = (
        "Consumer Price Index (CPI), 2024 As Base Year, Monthly"
        if table == INDEX_TABLE
        else "Percent Change In Consumer Price Index (CPI) "
        "Over Corresponding Period Of Previous Year, "
        "2024 As Base Year, Monthly"
    )
    if (
        meta["id"] != table
        or meta["frequency"] != "Monthly"
        or meta["title"] != expected_title
        or meta["dataSource"] != "SINGAPORE DEPARTMENT OF STATISTICS"
    ):
        raise InflationError("SingStatの表・基準年・出典が変わりました")
    selected = [one(meta["row"], lambda r, name=name: r["rowText"] == name) for name in names]
    if any(row["uoM"] != unit for row in selected):
        raise InflationError("SingStatの単位が変わりました")
    end = meta["endPeriod"]
    period = parse_month(end)
    data = checked(
        get_json(
            client,
            f"{BASE_URL}/tabledata/{table}",
            {
                "seriesNoORrowNo": ",".join(row["seriesNo"] for row in selected),
                "timeFilter": end,
                "limit": "100",
            },
        )
    )
    if data["id"] != table or data["frequency"] != "Monthly":
        raise InflationError("SingStatのデータ表が一致しません")
    values = {}
    for selected_row in selected:
        row = one(
            data["row"],
            lambda r, selected_row=selected_row: (
                r["seriesNo"] == selected_row["seriesNo"]
                and r["rowText"] == selected_row["rowText"]
                and r["uoM"] == unit
            ),
        )
        # timeFilterが無視された応答を黙って受け入れない。
        if len(row["columns"]) != 1:
            raise InflationError("SingStatの対象月の件数が不正です")
        column = one(row["columns"], lambda r: parse_month(r["key"]) == period)
        values[row["rowText"]] = column["value"]
    return period, values


def fetch(client: httpx.Client, env=None) -> dict:
    period, index = fetch_table(client, INDEX_TABLE, ["All Items"], "Index")
    yoy_period, yoy = fetch_table(client, YOY_TABLE, ["All Items", "Food"], "Per Cent")
    if period != yoy_period:
        raise InflationError("SingStatの指数と前年比の対象月が一致しません")
    return record("sg", period, index["All Items"], 2024, yoy["All Items"], yoy["Food"])
