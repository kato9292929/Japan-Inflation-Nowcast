"""日本CPIのキー無し経路（第1-1表のExcel）。合成のHTML・Excelで検証し、実通信はしない。"""

import io

import httpx
import openpyxl
import pytest

from jobs import refresh_inflation
from scrapers.inflation import jp_file
from scrapers.inflation.common import InflationError

LIST_URL = (
    "https://www.e-stat.go.jp/stat-search/files?page=1&amp;layout=datalist&amp;lid=000001494870"
)
SOKUHOU = f'<a href="{LIST_URL}">ファイル</a><a href="https://www.e-stat.go.jp/">e-Stat</a>'


def listing(period="2026年10月", released="2026-11-20", stat_id="000040525999"):
    def item(title, sid):
        return (
            f'<li class="stat-dataset_list-item"> 表番号 {title} 調査年月 {period} '
            f"公開（更新）日 {released} "
            f'<a href="/stat-search/file-download?statInfId={sid}&amp;fileKind=0">EXCEL</a>'
            f'<a href="/stat-search/file-download?statInfId={sid}&amp;fileKind=4">EXCEL</a></li>'
        )

    return (
        "<ul>"
        + item("1-1 中分類指数（全国） 月次", stat_id)
        + item("1-1 中分類指数（全国） 年平均", "000040526000")
        + item("1-2 中分類指数（東京都区部） 月次", "000040526002")
        + "</ul>"
    )


def workbook(rows_by_kind=None, title="中分類指数（全国）", food_code="0002", area="全国"):
    rows_by_kind = rows_by_kind or {
        "月次，指数": [("2026年9月", 102.2, 103.6), ("2026年10月", 103.1, 104.3)],
        "月次，前月比(％)": [("2026年9月", 0, -0.2), ("2026年10月", 0.8, 0.7)],
        "月次，前年同月比(％)": [("2026年9月", 2.1, 2.8), ("2026年10月", 2.3, 2.7)],
    }
    book = openpyxl.Workbook()
    book.remove(book.active)
    for i, (kind, data) in enumerate(rows_by_kind.items()):
        sheet = book.create_sheet(f"bm01-1 ({i + 1})")
        blank = [None] * 14
        rows = [list(blank) for _ in range(14)]
        rows[3][7:9] = ["統計名：", "2025年基準消費者物価指数"]
        rows[4][7:9] = ["統計表番号：", "第1-1表"]
        rows[5][7:9] = ["表題：", title]
        rows[6][7] = kind
        rows[8][11:14] = ["類・品目符号", "0001", food_code]
        rows[9][11:14] = ["類・品目", "総合", "食料"]
        for r in rows:
            sheet.append(r)
        for label, total, food in data:
            row = ["m01-1", *[None] * 7, label, "00000", area, None, total, food]
            sheet.append(row)
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def client(listing_html=None, content=None):
    def handler(request):
        url = str(request.url)
        if url == jp_file.SOKUHOU_URL:
            return httpx.Response(200, text=SOKUHOU)
        if "stat-search/files" in url:
            return httpx.Response(200, text=listing_html or listing())
        if "statInfId=000040525999&fileKind=0" in url:
            return httpx.Response(200, content=content or workbook())
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_reads_latest_month_from_table_1_1():
    result = jp_file.fetch(client())
    assert result["as_of"] == "2026-10"
    assert result["cpi_index"] == {"value": 103.1, "base_year": 2025, "base_value": 100}
    assert result["cpi_yoy"] == 2.3
    assert result["food_yoy"] == 2.7
    assert result["released_at"] == "2026-11-20T00:00:00+09:00"
    assert result["status"] == "ok" and result["stale"] is False


@pytest.mark.parametrize(
    "kwargs",
    [
        {"title": "中分類指数（東京都区部）"},
        {"food_code": "0003"},
        {"area": "東京都区部"},
    ],
)
def test_rejects_changed_table(kwargs):
    with pytest.raises(InflationError):
        jp_file.fetch(client(content=workbook(**kwargs)))


def test_rejects_listing_period_mismatch():
    with pytest.raises(InflationError):
        jp_file.fetch(client(listing_html=listing(period="2026年9月")))


def test_rejects_missing_yoy_sheet():
    rows = {"月次，指数": [("2026年10月", 103.1, 104.3)]}
    with pytest.raises(InflationError):
        jp_file.fetch(client(content=workbook(rows_by_kind=rows)))


def test_rejects_non_numeric_value():
    rows = {
        "月次，指数": [("2026年10月", 103.1, 104.3)],
        "月次，前年同月比(％)": [("2026年10月", "* ", 2.7)],
    }
    with pytest.raises(InflationError):
        jp_file.fetch(client(content=workbook(rows_by_kind=rows)))


def test_refresh_uses_file_route_without_app_id(monkeypatch, tmp_path):
    monkeypatch.delenv("ESTAT_APP_ID", raising=False)
    called = []
    monkeypatch.setattr(jp_file, "fetch", lambda c: called.append("file") or {"as_of": "2026-10"})
    api = lambda c: called.append("api") or {"as_of": "2026-10"}  # noqa: E731
    monkeypatch.setattr(refresh_inflation.jp, "fetch", api)
    refresh_inflation.fetch_jp(None)
    monkeypatch.setenv("ESTAT_APP_ID", "test-key")
    refresh_inflation.fetch_jp(None)
    assert called == ["file", "api"]
