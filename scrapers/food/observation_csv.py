"""食料 観測 CSV インポータ（店頭観測パネル, §8）。

前提スキーマ（手動観測 CSV）:
    obs_date,section,product,unit,honbody_yen,taxincl_yen,per100g_yen,label,stock

life_basket 形式（商品ID,分類,品名,...）とは別系統。店頭で撮った1日分の観測を
FoodRaw 互換レコードへ変換する。HTTP・robots は使わない（ローカル CSV）。
利用規約・著作権・関連法の遵守は運用者責任（§8）。生データは再配布しない。

方針（取り込み指示 2026-08-18 準拠）:
- 価格は税込（taxincl_yen）を採用。
- 肉（牛肉/豚肉/鶏肉/挽肉）は per100g_yen をマッチキーにする
  （unit=g, unit_size=100, price=per100g として ¥/100g に正準化）。per100g 空欄は
  unit_price 算出不能＝unmatched として扱い、値は捏造しない。
- stock が「在庫なし」の行は値が空。in_stock=False で取り込み、価格は None のまま。
- label の販促バッジは本モジュールの規則で is_promo を決める（手で事前判定しない）:
    販促(True): 広告の品 / 日替わり / 日替り / よりどり / まとめ
    非販促(False): おすすめ / 当店の品 / 冷凍 / 空欄 / その他
  （excl_promo は temporary な値引きを除く「基調」。おすすめ等の常設ラベルは値引きでない）
- section を CPI 食料 10 中分類へ写像（下記）。混在 section（乳飲料・挽肉 等）は
  商品名キーワードで補正する。指数の基準日・カテゴリ数・定義は変えない。
"""

from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any

from scrapers.base import SourceConfig

# --------------------------------------------------------------------------- #
# section -> CPI 食料 中分類
# --------------------------------------------------------------------------- #
SECTION_TO_CATEGORY: dict[str, str] = {
    "野菜": "野菜・海藻",
    "果物": "果物",
    "牛肉": "肉類",
    "豚肉": "肉類",
    "鶏肉": "肉類",
    "挽肉": "肉類",
    "魚": "魚介類",
    "惣菜": "調理食品",
    "パン": "穀類",
    "たまご": "乳卵類",
    "牛乳": "乳卵類",
    "乳製品": "乳卵類",
    "乳飲料": "乳卵類",  # 商品名で補正（豆乳→大豆製品, ジュース/コーヒー→飲料）
    "納豆": "大豆製品",
    "豆腐": "大豆製品",
    "冷凍": "調理食品",
    "酒": "酒類",
    "飲料": "飲料",
    "米": "穀類",
    "米飯": "調理食品",
    "調味料": "油脂・調味料",
    "乾麺": "穀類",
    "即席麺": "穀類",
    "カップ麺": "穀類",
    "パスタ": "穀類",
    "粉類": "穀類",
}

# 商品名キーワードによるカテゴリ補正（section の既定を上書き）。
_KEYWORD_CATEGORY: list[tuple[str, str]] = [
    ("豆乳", "大豆製品"),
    ("トマトジュース", "飲料"),
    ("野菜これ", "飲料"),
    ("充実野菜", "飲料"),
    ("タリーズ", "飲料"),
    ("餃子の皮", "穀類"),
    ("もずく", "野菜・海藻"),
    ("めかぶ", "野菜・海藻"),
    ("わかめ", "野菜・海藻"),
]

# is_promo=True とみなす販促バッジ（temporary な値引き）。
_PROMO_LABELS = {"広告の品", "日替わり", "日替り", "よりどり", "まとめ"}

# unit フィールドのパース用トークン。
_MASS_UNITS = ("kg", "g")
_VOL_UNITS = ("ml", "l")
_COUNT_UNITS = ("枚", "個入", "個", "コ", "玉入", "玉", "切", "袋", "本入", "本", "パック", "束", "人前", "缶")


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    s = str(value).replace(",", "").replace("¥", "").replace("円", "").strip()
    if not s:
        return None
    try:
        return int(float(s))
    except ValueError:
        return None


def classify_category(section: str, product: str) -> str | None:
    """section と商品名から CPI 中分類を決める。未知 section は None（呼び手が警告）。"""
    base = SECTION_TO_CATEGORY.get(section.strip())
    for kw, cat in _KEYWORD_CATEGORY:
        if kw in product:
            return cat
    return base


def is_promo_label(label: str) -> bool:
    """販促バッジ規則。temporary な値引きバッジのみ True。"""
    return label.strip() in _PROMO_LABELS


def parse_unit(unit_field: str, product: str) -> tuple[str | None, float | None]:
    """unit 文字列（"5kg" "45g×3" "6枚" "1袋" "目安" 等）→ (正準 unit トークン, unit_size)。

    - 質量/容量: "45g×3" のような ×N は総量に展開（135g）。返す unit は g/ml/kg/l。
    - 個数: "6枚"→(枚,6)、"1袋"→(袋,1)、"6個入"→(個,6)。
    - "目安"（肉の量り売り）: 呼び手が per100g 経路を使うため (None, None) を返す。
    - 解釈不能: (None, None)。呼び手が unmatched として扱う。
    """
    u = (unit_field or "").strip().replace("　", "")
    if not u or u == "目安":
        return (None, None)

    # 質量・容量（×N 展開）。kg/ml/l を g より先に見て取りこぼさない。
    m = re.search(r"(\d+(?:\.\d+)?)\s*(kg|ml|ℓ|l|g)", u, re.IGNORECASE)
    if m:
        size = float(m.group(1))
        token = m.group(2).lower().replace("ℓ", "l")
        mult = re.search(r"[×xX]\s*(\d+)", u)
        if mult:
            size *= float(mult.group(1))
        return (token, size)

    # 個数（先頭の数量 or 明示数量）。emit するトークンは etl の正準 count 集合に合わせる。
    _COUNT_CANON = {
        "個入": "個", "個": "個", "コ": "個",
        "枚": "枚", "玉入": "玉", "玉": "玉",
        "本入": "本", "本": "本", "切": "切", "袋": "袋",
        "パック": "パック", "束": "束", "缶": "缶", "人前": "パック",
    }
    for cu in _COUNT_UNITS:
        mm = re.search(r"(\d+)\s*" + re.escape(cu), u)
        if mm:
            return (_COUNT_CANON.get(cu, cu), float(mm.group(1)))
    # "1/4" 等の分数パック → 1パック相当（同一 SKU を日次で追う前提で size=1）
    if re.fullmatch(r"\d+/\d+", u):
        return ("パック", 1.0)
    # 数量なしの単位語だけ（"1パック" は上でヒット。念のため）
    return (None, None)


class ObservationFoodImporter:
    """観測 CSV（obs_date,section,product,unit,honbody_yen,taxincl_yen,per100g_yen,label,stock）
    → FoodRaw 互換レコード list。"""

    kind = "food"

    def __init__(self, config: SourceConfig, **_: Any) -> None:
        self.config = config
        self.warnings: list[str] = []

    def run(self) -> list[dict[str, Any]]:
        path_str = self.config.path
        if not path_str:
            return []
        path = Path(path_str)
        if not path.exists():
            return []

        records: list[dict[str, Any]] = []
        seen_ids: dict[str, int] = {}
        with path.open(encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                rec = self._row_to_record(row, seen_ids)
                if rec is not None:
                    records.append(rec)
        return records

    def _row_to_record(self, row: dict[str, str], seen_ids: dict[str, int]) -> dict[str, Any] | None:
        section = (row.get("section") or "").strip()
        product = (row.get("product") or "").strip()
        if not product:
            return None

        category = classify_category(section, product)
        if category is None:
            self.warnings.append(f"unknown section '{section}' -> category None: {product}")

        in_stock = (row.get("stock") or "").strip() != "在庫なし"
        label = (row.get("label") or "").strip()
        promo = is_promo_label(label)

        taxincl = _to_int(row.get("taxincl_yen"))
        per100g = _to_int(row.get("per100g_yen"))
        unit_field = (row.get("unit") or "").strip()

        # 肉（per100g をマッチキー）: unit=g, size=100, price=per100g で ¥/100g に正準化。
        # section ではなく確定 category で判定（餃子の皮=挽肉 section だが穀類 等を除く）。
        if category == "肉類":
            if per100g is not None:
                unit_token, unit_size, price = "g", 100.0, per100g
            else:
                # per100g 無し（パック単価のみ）＝比較不能。値は捏造しない。
                unit_token, unit_size, price = None, None, taxincl
        else:
            unit_token, unit_size = parse_unit(unit_field, product)
            price = taxincl
            # 肉以外の「目安」（魚のサク/切り身パック等）は per100g 表示が無い。
            # パック単位（¥/パック）で日次比較できるよう 1 パック相当に落とす。
            if unit_token is None and unit_field.strip() == "目安":
                unit_token, unit_size = "パック", 1.0
            if in_stock and unit_token is None:
                self.warnings.append(f"unit parse failed '{unit_field}': {product}")

        # 在庫なし行は価格空。捏造しない。
        if not in_stock:
            price = None

        # 冪等キー item_id: 正規化 product+unit のスラッグ（同一商品は日をまたいで同一）。
        base_id = re.sub(r"\s+", "", f"{product}_{unit_field}").lower()
        if base_id in seen_ids:
            seen_ids[base_id] += 1
            item_id = f"{base_id}#{seen_ids[base_id]}"
        else:
            seen_ids[base_id] = 0
            item_id = base_id

        return {
            "source": self.config.id,
            "item_id": item_id,
            "category": category,
            "product_name": product,
            "brand": "",  # 観測 CSV はブランドを product に内包
            "unit": unit_token,
            "unit_size": unit_size,
            "price": price,
            "is_promo": promo,
            "in_stock": in_stock,
            "raw_payload": dict(row),
        }
