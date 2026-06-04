"""無償ダッシュボードの描画ロジック（読み取り専用, §0, §1）。

API の無償エンドポイント（JP-INFL-NOWCAST の latest + 直近 90 日）から得たデータを、
人間向けの headline ビューに整形する純粋関数群。実通信はしない（API レスポンス形を入力に取る）。

§0 遵守: 画面に必ず「部分カバーのナウキャスト（速報）」「coverage_pct 明示」「総務省の
公式統計とは異なる」旨を出す。「公式 CPI」「CPI そのもの」と誤認させる表記は入れない。
"""

from __future__ import annotations

import html
from typing import Any

DISCLAIMER = (
    "This is an independent nowcast (速報), NOT official CPI. "
    "It covers only part of the CPI basket; see coverage_pct."
)
BANNER_JA = (
    "独立系インフレ・ナウキャスト（速報）。総務省の公式統計とは異なる、部分カバーの指数です。"
)


def coverage_label(coverage_pct: float | None) -> str:
    """coverage_pct を画面コピーに整形（§0「CPI バスケットの約 X% をカバー」）。"""
    if coverage_pct is None:
        return "カバー率: 不明"
    return f"CPI バスケットの約 {coverage_pct:.1f}% をカバー（部分指数・100% 未満）"


def build_headline_view(latest: dict[str, Any], history: list[dict[str, Any]]) -> dict[str, Any]:
    """無償 API レスポンスから headline ビュー（描画用 dict）を作る。

    latest: /v1/indices/{code}/latest のレスポンス（IndexValueOut 形）。
    history: /v1/indices/{code}/history のレスポンス（list[IndexValueOut]）。
    """
    coverage = latest.get("coverage_pct")
    points = [
        {"date": str(h.get("date")), "value": h.get("value")}
        for h in history
        if h.get("value") is not None
    ]
    return {
        "index_code": latest.get("index_code"),
        "as_of": str(latest.get("date")),
        "value": round(float(latest["value"]), 2) if latest.get("value") is not None else None,
        "coverage_pct": coverage,
        "coverage_label": coverage_label(coverage),
        "is_partial": (coverage is not None and coverage < 100.0),
        "yoy_pct": latest.get("yoy_pct"),
        "mom_pct": latest.get("mom_pct"),
        "wow_pct": latest.get("wow_pct"),
        "disclaimer": latest.get("disclaimer") or DISCLAIMER,
        "banner_ja": BANNER_JA,
        "history": points,
        "n_points": len(points),
    }


def _spark(points: list[dict[str, Any]]) -> str:
    """履歴を簡易スパークライン（block 文字）に変換する。"""
    vals = [float(p["value"]) for p in points if p.get("value") is not None]
    if not vals:
        return ""
    lo, hi = min(vals), max(vals)
    blocks = "▁▂▃▄▅▆▇█"
    if hi == lo:
        return blocks[0] * len(vals)
    return "".join(blocks[int((v - lo) / (hi - lo) * (len(blocks) - 1))] for v in vals)


def render_html(view: dict[str, Any]) -> str:
    """headline ビューを最小限の静的 HTML に描画する（読み取り専用）。"""
    code = html.escape(str(view.get("index_code")))
    value = view.get("value")
    cov = html.escape(view["coverage_label"])
    disclaimer = html.escape(view["disclaimer"])
    banner = html.escape(view["banner_ja"])
    spark = _spark(view.get("history") or [])
    as_of = html.escape(view["as_of"])
    yoy = view.get("yoy_pct")
    yoy_html = f"<span class='yoy'>YoY: {yoy:.2f}%</span>" if yoy is not None else ""

    return f"""<!DOCTYPE html>
<html lang="ja">
<head><meta charset="utf-8"><title>Japan Inflation Nowcast</title></head>
<body>
  <main>
    <p class="banner" role="alert">{banner}</p>
    <h1>{code}</h1>
    <p class="value">最新値: <strong>{value}</strong>（as of {as_of}）{yoy_html}</p>
    <p class="coverage">{cov}</p>
    <p class="spark" aria-label="直近 {view['n_points']} 日">{spark}</p>
    <p class="disclaimer">{disclaimer}</p>
  </main>
</body>
</html>"""
