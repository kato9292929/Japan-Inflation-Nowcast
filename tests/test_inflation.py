"""公式スキーマに沿った合成応答で検証。実取得値として公開しない。"""

import copy
import json
from pathlib import Path

import httpx
import pytest

from jobs import refresh_inflation
from scrapers.inflation import jp, kr, sg
from scrapers.inflation.common import InflationError, empty_record, get_json, number, record


def client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def japan_payloads():
    classes = []
    for name, entries in {
        "tab": [("idx", "指数"), ("yoy", "前年同月比")],
        "cat01": [("all", "総合"), ("food", "食料")],
        "area": [("national", "全国")],
        "time": [("t1", "2026年6月"), ("t2", "2026年7月"), ("year", "2026年")],
    }.items():
        classes.append(
            {"@id": name, "CLASS": [{"@code": code, "@name": label} for code, label in entries]}
        )
    meta = {
        "GET_META_INFO": {
            "RESULT": {"STATUS": 0},
            "METADATA_INF": {
                "TABLE_INF": {"TITLE": {"$": "消費者物価指数（2025年基準）"}},
                "CLASS_INF": {"CLASS_OBJ": classes},
            },
        }
    }
    values = [
        {"@tab": tab, "@cat01": cat, "@area": "national", "@time": period, "$": value}
        for period in ["t2", "t1"]
        for tab, cat, value in [("idx", "all", "102"), ("yoy", "all", "2"), ("yoy", "food", "3")]
    ]
    data = {
        "GET_STATS_DATA": {
            "RESULT": {"STATUS": 0},
            "STATISTICAL_DATA": {"RESULT_INF": {}, "DATA_INF": {"VALUE": values}},
        }
    }
    return meta, data


def test_japan_resolves_metadata_and_latest_month():
    meta, data = japan_payloads()

    def handler(request):
        assert request.url.params["appId"] == "test-key"
        assert request.url.params["statsDataId"] == jp.TABLE_ID
        if request.url.path.endswith("getMetaInfo"):
            return httpx.Response(200, json=meta)
        assert request.url.params["cdArea"] == "national"
        assert request.url.params["cdTime"] == "t1,t2"
        return httpx.Response(200, json=data)

    result = jp.fetch(client(handler), {"ESTAT_APP_ID": "test-key"})
    assert (result["as_of"], result["cpi_yoy"], result["food_yoy"]) == ("2026-07", 2, 3)
    assert result["released_at"] is None
    assert result["cpi_index"]["base_year"] == 2025


@pytest.mark.parametrize("failure", ["pagination", "duplicate", "missing", "error", "region"])
def test_japan_rejects_incomplete_or_ambiguous_data(failure):
    meta, data = japan_payloads()
    body = data["GET_STATS_DATA"]["STATISTICAL_DATA"]
    rows = body["DATA_INF"]["VALUE"]
    if failure == "pagination":
        body["RESULT_INF"]["NEXT_KEY"] = 10001
    elif failure == "duplicate":
        rows.append(copy.deepcopy(rows[0]))
    elif failure == "missing":
        rows[0]["$"] = "-"
    elif failure == "error":
        data["GET_STATS_DATA"]["RESULT"]["STATUS"] = 100
    else:
        rows[0]["@area"] = "tokyo"
    with pytest.raises(InflationError):
        jp.fetch(
            client(
                lambda req: httpx.Response(
                    200, json=meta if req.url.path.endswith("getMetaInfo") else data
                )
            ),
            {"ESTAT_APP_ID": "test-key"},
        )


def korea_rows():
    # 全国コードはテスト専用。実コードを推測して固定しない。
    return [
        {
            "ORG_ID": "101",
            "TBL_ID": kr.TABLE_ID,
            "TBL_NM": "소비자물가지수",
            "ITM_ID": "T",
            "C1": "TEST_NATIONAL",
            "C1_NM": "전국",
            "PRD_SE": "M",
            "PRD_DE": period,
            "DT": value,
            "UNIT_NM": "2020＝100",
        }
        for period, value in [("202607", "104"), ("202507", "100")]
    ]


def test_korea_derives_yoy_without_confusing_regions_or_release_dates():
    def handler(req):
        assert req.url.path == "/openapi/Param/statisticsParameterData.do"
        assert req.url.params["objL1"] == "TEST_NATIONAL"
        assert req.url.params["newEstPrdCnt"] == "13"
        return httpx.Response(200, json=korea_rows())

    result = kr.fetch(
        client(handler), {"KOSIS_API_KEY": "key", "KOSIS_CPI_REGION_CODE": "TEST_NATIONAL"}
    )
    assert result["cpi_yoy"] == 4
    assert result["yoy_method"] == "index_ratio"
    assert result["food_yoy"] is None
    assert result["metric_status"]["food_yoy"] == "not_supported"
    assert result["released_at"] is None


@pytest.mark.parametrize("failure", ["region", "base", "duplicate", "previous", "error"])
def test_korea_fails_closed(failure):
    rows = korea_rows()
    if failure == "region":
        rows[0]["C1_NM"] = "서울"
    elif failure == "base":
        rows[0]["UNIT_NM"] = "2025=100"
    elif failure == "duplicate":
        rows.append(rows[0])
    elif failure == "previous":
        rows.pop()
    else:
        rows = {"err": "20", "errMsg": "error"}
    with pytest.raises(InflationError):
        kr.fetch(
            client(lambda _: httpx.Response(200, json=rows)),
            {"KOSIS_API_KEY": "key", "KOSIS_CPI_REGION_CODE": "TEST_NATIONAL"},
        )


def singapore_handler(req):
    table = req.url.path.split("/")[-1]
    is_index = table == sg.INDEX_TABLE
    unit = "Index" if is_index else "Per Cent"
    rows = [
        {"seriesNo": "test_all", "rowText": "All Items", "uoM": unit},
        {"seriesNo": "test_food", "rowText": "Food", "uoM": unit},
    ]
    base = {"id": table, "frequency": "Monthly"}
    if "/metadata/" in req.url.path:
        prefix = "" if is_index else "Percent Change In "
        suffix = "" if is_index else " Over Corresponding Period Of Previous Year"
        base.update(
            title=f"{prefix}Consumer Price Index (CPI){suffix}, 2024 As Base Year, Monthly",
            dataSource="SINGAPORE DEPARTMENT OF STATISTICS",
            endPeriod="2026 Jul",
            row=rows,
        )
        return httpx.Response(200, json={"StatusCode": 200, "Data": {"records": base}})
    assert req.url.params["timeFilter"] == "2026 Jul"
    assert req.url.params["seriesNoORrowNo"] == ("test_all" if is_index else "test_all,test_food")
    for row in rows:
        row["columns"] = [{"key": "2026 Jul", "value": "102" if is_index else "2"}]
    base["row"] = rows
    return httpx.Response(200, json={"StatusCode": 200, "Data": base})


def test_singapore_reads_published_yoy():
    result = sg.fetch(client(singapore_handler))
    assert result["cpi_index"]["value"] == 102
    assert result["cpi_yoy"] == result["food_yoy"] == 2
    assert result["yoy_method"] == "published"
    assert result["as_of"] == "2026-07"


@pytest.mark.parametrize("failure", ["period", "base", "missing", "unit", "error"])
def test_singapore_rejects_changed_schema_or_mismatched_periods(failure):
    def handler(req):
        response = singapore_handler(req).json()
        if req.url.path.endswith(sg.YOY_TABLE):
            data = response["Data"]
            if "records" in data:
                if failure == "base":
                    data["records"]["title"] = "旧基準"
                if failure == "unit":
                    data["records"]["row"][0]["uoM"] = "Index"
            elif failure == "period":
                data["row"][0]["columns"][0]["key"] = "2026 Jun"
            elif failure == "missing":
                data["row"][0]["columns"][0]["value"] = "na"
            if failure == "error":
                response["StatusCode"] = 404
        return httpx.Response(200, json=response)

    with pytest.raises(InflationError):
        sg.fetch(client(handler))


@pytest.mark.parametrize("value", [None, True, "-", "na", "NaN", "Infinity", ""])
def test_missing_values_are_not_zero(value):
    with pytest.raises(InflationError):
        number(value)


def test_http_error_does_not_expose_key():
    with pytest.raises(InflationError) as caught:
        get_json(
            client(lambda _: httpx.Response(403)), "https://example.invalid", {"apiKey": "SECRET"}
        )
    assert "SECRET" not in str(caught.value)
    assert caught.value.__suppress_context__


def test_refresh_failure_preserves_provenance_and_recovery(tmp_path, monkeypatch):
    previous = record("jp", "2026-07", 102, 2025, 2, 3)
    path = tmp_path / "jp.json"
    refresh_inflation.atomic_write(path, previous)

    def fail(_):
        raise InflationError("SECRET")

    monkeypatch.setitem(refresh_inflation.ADAPTERS, "jp", fail)
    assert not refresh_inflation.refresh("jp", tmp_path, client(lambda _: None))
    failed = json.loads(path.read_text())
    assert failed["stale"] and failed["status"] == "refresh_failed"
    assert failed["fetched_at"] == previous["fetched_at"]
    assert failed["as_of"] == previous["as_of"]
    assert "SECRET" not in path.read_text()
    monkeypatch.setitem(refresh_inflation.ADAPTERS, "jp", lambda _: previous.copy())
    assert refresh_inflation.refresh("jp", tmp_path, client(lambda _: None))
    assert json.loads(path.read_text())["status"] == "ok"
    assert not list(tmp_path.glob("*.tmp"))


def test_cli_continues_other_countries_and_exits_nonzero(tmp_path, monkeypatch):
    for country in ["jp", "kr", "sg"]:
        monkeypatch.setitem(
            refresh_inflation.ADAPTERS,
            country,
            lambda _, c=country: record(c, "2026-07", 102, 2025, 2),
        )

    def fail(_):
        raise InflationError("失敗")

    monkeypatch.setitem(refresh_inflation.ADAPTERS, "kr", fail)
    assert refresh_inflation.main(["--output-dir", str(tmp_path)]) == 1
    assert json.loads((tmp_path / "jp.json").read_text())["status"] == "ok"
    assert json.loads((tmp_path / "kr.json").read_text())["stale"]
    assert json.loads((tmp_path / "sg.json").read_text())["status"] == "ok"
    assert not (tmp_path / ".refresh.lock").exists()


def test_initial_files_contain_no_invented_data():
    for country in ["jp", "kr", "sg"]:
        value = json.loads(Path(f"data/inflation/{country}.json").read_text())
        if value["status"] == "not_fetched":
            assert value == empty_record(country)
        else:
            assert value["source"] == empty_record(country)["source"]
            assert "as_of" in value
