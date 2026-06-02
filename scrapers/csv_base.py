"""CSV インポータ基底（公式統計 / 手動パネルのローカル CSV 取り込み, §8）。

スクレイピングではなくローカル CSV を読むため、HTTP・robots・レート制限は不要。
既存スクレイパと互換の ``.run()`` を持ち、raw スキーマに一致する dict レコードの list を
返す（etl.*.upsert_raw がそのまま読める契約）。

法務（§8）: 公式統計・手動パネルでも、利用規約・著作権・関連法の遵守は運用者責任。
生データは内部保存のみ・再配布しない。元 CSV 行は raw_payload に保持（監査用）。

安全既定: config/sources.yaml に csv ソースが無ければ何も取り込まない。
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from scrapers.base import SourceConfig


def to_float(value: Any) -> float | None:
    if value is None:
        return None
    s = str(value).replace(",", "").replace("¥", "").replace("円", "").strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def to_int(value: Any) -> int | None:
    f = to_float(value)
    return int(f) if f is not None else None


def to_bool(value: Any) -> bool | None:
    if value is None:
        return None
    s = str(value).strip().lower()
    if s == "":
        return None
    if s in {"true", "1", "yes", "y", "t", "特売", "セール"}:
        return True
    if s in {"false", "0", "no", "n", "f"}:
        return False
    return None


def _clean_str(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


class CsvImporter:
    """CSV を raw レコード list に変換する基底。サブクラスがフィールド型を定義する。"""

    kind: str = "base"
    id_field: str = "id"
    float_fields: tuple[str, ...] = ()
    int_fields: tuple[str, ...] = ()
    bool_fields: tuple[str, ...] = ()
    # str として扱うフィールド（サブクラスで定義）。
    str_fields: tuple[str, ...] = ()

    def __init__(
        self,
        config: SourceConfig,
        *,
        user_agent: str | None = None,  # csv では未使用（コンストラクタ互換のため受ける）
        contact: str | None = None,
        **_: Any,
    ) -> None:
        self.config = config

    def _coerce(self, field: str, value: Any) -> Any:
        if field in self.float_fields:
            return to_float(value)
        if field in self.int_fields:
            return to_int(value)
        if field in self.bool_fields:
            return to_bool(value)
        return _clean_str(value)

    def run(self) -> list[dict[str, Any]]:
        """config.path の CSV を column_map で raw フィールドへ写像して返す。

        - column_map: CSV 列名 -> raw フィールド名。
        - id_field が空/欠損の行はスキップ。
        - 元行全体を raw_payload に保持。
        - source は config.id を付与（既存 upsert 契約に合わせる）。
        """
        path_str = self.config.path
        if not path_str:
            return []
        path = Path(path_str)
        if not path.exists():
            return []

        column_map = self.config.column_map or {}
        records: list[dict[str, Any]] = []
        with path.open(encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                record: dict[str, Any] = {"source": self.config.id}
                for csv_col, raw_field in column_map.items():
                    record[raw_field] = self._coerce(raw_field, row.get(csv_col))
                # id が無い行はスキップ（識別不能）。
                if not record.get(self.id_field):
                    continue
                record["raw_payload"] = dict(row)
                records.append(record)
        return records
