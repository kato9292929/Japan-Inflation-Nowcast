"""日本CPIをキー無しで取る経路（ESTAT_APP_ID が無いとき）。

総務省の全国速報ページ → e-Stat の当月ファイル一覧 → 第1-1表「中分類指数（全国）月次」の
Excel をたどり、表の名前・符号・地域・対象月を照合してから値を読む。どこかが合わなければ
InflationError で止める（古い値を最新として出さない）。robots.txt で禁止されていない
パス（stat.go.jp /data/cpi/、e-stat.go.jp /stat-search/）だけを使う。
"""

from __future__ import annotations

import html
import io
import re

import httpx

from .common import InflationError, month, number, record

SOKUHOU_URL = "https://www.stat.go.jp/data/cpi/sokuhou/tsuki/index-z.html"
ESTAT = "https://www.e-stat.go.jp"
TABLE_LABEL = "中分類指数（全国）"
SHEETS = {"月次，指数": "index", "月次，前年同月比(％)": "yoy"}
CODES = {"0001": "総合", "0002": "食料"}


def get(client: httpx.Client, url: str) -> httpx.Response:
    try:
        response = client.get(url, headers={"Accept": "*/*"}, follow_redirects=True)
        response.raise_for_status()
        return response
    except httpx.HTTPError:
        raise InflationError("公的サイトの通信に失敗しました") from None


def find_list_url(page: str) -> str:
    """全国速報ページから、e-Stat の当月ファイル一覧（lid）へのリンクを1件だけ取る。"""
    pattern = r'href="(https://www\.e-stat\.go\.jp/stat-search/files\?[^"]*lid=\d+[^"]*)"'
    links = set(re.findall(pattern, page))
    if len(links) != 1:
        raise InflationError("全国速報ページからe-Statのファイル一覧を特定できません")
    return html.unescape(links.pop())


def find_table(listing: str) -> tuple[str, str, str]:
    """一覧から第1-1表（全国・月次）の Excel を1件だけ取る。(statInfId, 調査年月, 公開日)"""
    found = []
    for block in listing.split("stat-dataset_list-item")[1:]:
        text = html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", block)))
        if not re.search(r"表番号\s*1-1\s*中分類指数（全国）\s*月次", text):
            continue
        ids = set(re.findall(r"statInfId=(\d+)&(?:amp;)?fileKind=0", block))
        period = re.search(r"調査年月\s*(\d{4})年\s*(\d{1,2})月", text)
        released = re.search(r"公開（更新）日\s*(\d{4}-\d{2}-\d{2})", text)
        if len(ids) == 1 and period and released:
            found.append((ids.pop(), month(f"{period[1]}-{int(period[2]):02d}"), released[1]))
    if len(found) != 1:
        raise InflationError("e-Statの一覧から第1-1表（全国・月次）を特定できません")
    return found[0]


def parse_table(content: bytes) -> dict:
    """第1-1表の Excel から、最新月の総合指数・総合前年比・食料前年比を読む。"""
    try:
        import openpyxl

        book = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception:
        raise InflationError("第1-1表のExcelを開けません") from None
    values: dict[str, dict] = {}
    for sheet in book.worksheets:
        rows = list(sheet.iter_rows(values_only=True))
        if len(rows) < 15:
            continue
        header = {rows[i][8] for i in (3, 4, 5)} | {rows[6][7]}
        kind = SHEETS.get(rows[6][7])
        if kind is None:
            continue
        if not {"2025年基準消費者物価指数", "第1-1表", TABLE_LABEL} <= header:
            raise InflationError("第1-1表の統計名・表番号・基準年が変わりました")
        columns = {}
        for code, name in CODES.items():
            hits = [i for i, c in enumerate(rows[8]) if c == code]
            if len(hits) != 1 or rows[9][hits[0]] != name:
                raise InflationError("第1-1表の類・品目符号が変わりました")
            columns[name] = hits[0]
        data = [r for r in rows[14:] if r and r[0]]
        if not data or any(r[10] != "全国" for r in data):
            raise InflationError("第1-1表の地域が全国ではありません")
        latest = data[-1]
        matched = re.fullmatch(r"(\d{4})年(\d{1,2})月", str(latest[8]).strip())
        if not matched:
            raise InflationError("第1-1表の時間軸が月次ではありません")
        period = month(f"{matched[1]}-{int(matched[2]):02d}")
        values[kind] = {"period": period, **{name: latest[col] for name, col in columns.items()}}
    if set(values) != {"index", "yoy"}:
        raise InflationError("第1-1表に指数・前年同月比のシートがそろっていません")
    if values["index"]["period"] != values["yoy"]["period"]:
        raise InflationError("指数と前年同月比の対象月が一致しません")
    return values


def fetch(client: httpx.Client, env=None) -> dict:
    list_url = find_list_url(get(client, SOKUHOU_URL).text)
    stat_inf_id, listed_period, released = find_table(get(client, list_url).text)
    url = f"{ESTAT}/stat-search/file-download?statInfId={stat_inf_id}&fileKind=0"
    content = get(client, url).content
    values = parse_table(content)
    period = values["index"]["period"]
    if period != listed_period:
        raise InflationError("一覧の調査年月と表の最新月が一致しません")
    result = record(
        "jp",
        period,
        values["index"]["総合"],
        2025,
        values["yoy"]["総合"],
        number(values["yoy"]["食料"]),
    )
    result["released_at"] = f"{released}T00:00:00+09:00"
    return result
