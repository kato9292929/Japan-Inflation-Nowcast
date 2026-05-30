"""pytest 共通フィクスチャ。

リポジトリルートを sys.path に入れて、トップレベルパッケージ（storage, api, ...）を
import できるようにする。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture
def repo_root() -> Path:
    return ROOT


@pytest.fixture
def config_dir() -> Path:
    return ROOT / "config"
