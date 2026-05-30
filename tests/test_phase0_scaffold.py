"""Phase 0 受け入れ条件のテスト（§9）。

- 構成パッケージが import できる。
- SQLModel テーブルが §5 どおり登録される。
- config スキーマが読める。
- sources.yaml の安全既定（空＝何も取得しない, §8）。
- 「公式 CPI」誤認防止の表記がある（§0）。

実装ロジックは Phase 1 以降。ここでは枠の健全性だけを検査する。
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------- #
# import 健全性
# --------------------------------------------------------------------------- #
MODULES = [
    "storage.db",
    "storage.models",
    "scrapers.base",
    "etl.housing",
    "etl.food",
    "index_engine.hedonic",
    "index_engine.laspeyres",
    "index_engine.flow",
    "index_engine.food",
    "index_engine.composite",
    "index_engine.aggregate",
    "api.app",
    "api.x402",
    "jobs.daily",
]


@pytest.mark.parametrize("module", MODULES)
def test_modules_importable(module: str) -> None:
    assert importlib.import_module(module) is not None


# --------------------------------------------------------------------------- #
# データモデル（§5）
# --------------------------------------------------------------------------- #
def test_expected_tables_registered() -> None:
    from sqlmodel import SQLModel

    import storage.models  # noqa: F401  テーブル登録

    expected = {
        "listings_raw",
        "listings_clean",
        "food_raw",
        "food_clean",
        "index_values",
        "methodology_versions",
    }
    assert expected <= set(SQLModel.metadata.tables.keys())


def test_index_values_has_coverage_and_methodology_columns() -> None:
    """合成の coverage_pct と methodology_version は必須カラム（§0, §6-4）。"""
    from sqlmodel import SQLModel

    import storage.models  # noqa: F401

    cols = set(SQLModel.metadata.tables["index_values"].columns.keys())
    for required in ("coverage_pct", "methodology_version", "base_date", "series_type"):
        assert required in cols


def test_init_db_creates_tables(tmp_path, monkeypatch) -> None:
    """SQLite で init_db が冪等にテーブルを作れる。"""
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    import storage.db as db

    db.get_settings.cache_clear()
    db.get_engine.cache_clear()

    db.init_db()
    db.init_db()  # 冪等

    from sqlalchemy import inspect

    names = set(inspect(db.get_engine()).get_table_names())
    assert "index_values" in names

    db.get_settings.cache_clear()
    db.get_engine.cache_clear()


# --------------------------------------------------------------------------- #
# config スキーマ
# --------------------------------------------------------------------------- #
def test_sources_empty_default_fetches_nothing() -> None:
    """安全既定（§8）: sources.yaml の housing/food は空 -> 何も取得しない。"""
    from scrapers.base import load_sources

    assert load_sources("housing") == []
    assert load_sources("food") == []


def test_load_sources_missing_file_is_safe(tmp_path) -> None:
    from scrapers.base import load_sources

    assert load_sources("housing", path=tmp_path / "nope.yaml") == []


def test_baskets_config_parses_and_has_weights() -> None:
    data = yaml.safe_load((ROOT / "config" / "baskets.yaml").read_text(encoding="utf-8"))
    assert "composite_weights" in data
    assert "JP-INFL-FOOD" in data["composite_weights"]
    assert "JP-INFL-HOUSING" in data["composite_weights"]
    assert data["food"]["categories"]


def test_normalize_dicts_present() -> None:
    for name in ("ward.yaml", "station.yaml", "address.yaml"):
        path = ROOT / "config" / "normalize" / name
        assert path.exists()
        yaml.safe_load(path.read_text(encoding="utf-8"))  # 例外なく読める


def test_env_example_has_required_keys() -> None:
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    for key in (
        "DATABASE_URL",
        "X402_FACILITATOR_URL",
        "X402_RECIPIENT_ADDRESS",
        "X402_CHAIN",
        "X402_ASSET",
        "SCRAPER_USER_AGENT",
        "SCRAPER_CONTACT",
        "BASE_DATE",
        "REBASE_POLICY",
    ):
        assert key in text


# --------------------------------------------------------------------------- #
# 非交渉制約: 「公式 CPI」誤認防止（§0）
# --------------------------------------------------------------------------- #
def test_api_carries_not_official_disclaimer() -> None:
    from api.app import DISCLAIMER, IndexValueOut

    assert "NOT official CPI" in DISCLAIMER
    # 値オブジェクトは coverage_pct を持つ（§0）
    assert "coverage_pct" in IndexValueOut.model_fields


def test_readme_and_methodology_flag_nowcast_not_cpi() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    methodology = (ROOT / "methodology" / "methodology.md").read_text(encoding="utf-8")
    assert "公式 CPI" in readme  # 誤認防止の明示（否定文脈）
    assert "coverage_pct" in readme
    assert "ナウキャスト" in methodology
