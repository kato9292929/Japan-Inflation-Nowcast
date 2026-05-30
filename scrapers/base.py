"""抽象スクレイパアダプタと遵守機構（§8 ハード制約）。

このモジュールが内蔵する遵守機構:
- robots.txt の取得・尊重（不許可パスは取得しない）。
- レート制限（1 req / 数秒）+ 指数バックオフ + 同時実行 1。
- User-Agent / 問い合わせ先の明示。
- ``config/sources.yaml`` が空なら何も取得しない安全既定。

重要（§8）: 各ソースの利用規約・著作権・関連法の遵守は運用者責任である。
コード側は法的判断をしない。生データは内部保存のみで再配布しない。
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
SOURCES_PATH = CONFIG_DIR / "sources.yaml"


@dataclass(frozen=True)
class SourceConfig:
    """1 ソースの設定（config/sources.yaml の 1 エントリ）。"""

    id: str
    base_url: str
    enabled: bool = False
    rate_limit_seconds: float = 5.0
    max_concurrency: int = 1
    respect_robots: bool = True
    start_paths: list[str] = field(default_factory=list)


def load_sources(kind: str, path: Path = SOURCES_PATH) -> list[SourceConfig]:
    """``config/sources.yaml`` から指定種別（'housing' / 'food'）のソースを読む。

    安全既定（§8）: ファイルが無い / 空 / 当該種別が無い場合は空リストを返す
    （= 何も取得しない）。enabled=False のソースも除外する。
    """
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries = data.get(kind) or []
    sources: list[SourceConfig] = []
    for entry in entries:
        cfg = SourceConfig(
            id=entry["id"],
            base_url=entry["base_url"],
            enabled=bool(entry.get("enabled", False)),
            rate_limit_seconds=float(entry.get("rate_limit_seconds", 5.0)),
            max_concurrency=int(entry.get("max_concurrency", 1)),
            respect_robots=bool(entry.get("respect_robots", True)),
            start_paths=list(entry.get("start_paths", [])),
        )
        if cfg.enabled:
            sources.append(cfg)
    return sources


class BaseScraper(abc.ABC):
    """全アダプタの基底。遵守機構を提供し、解析はサブクラスに委ねる。

    サブクラスは ``parse`` のみを実装する。取得（fetch）は基底が遵守機構付きで行う。
    """

    kind: str = "base"

    def __init__(self, config: SourceConfig, *, user_agent: str, contact: str) -> None:
        self.config = config
        self.user_agent = user_agent
        self.contact = contact

    # --- 遵守機構（Phase 1 で実装。Phase 0 はシグネチャのみ）-------------------
    def is_allowed(self, path: str) -> bool:
        """robots.txt に基づき path 取得可否を判定（§8）。"""
        raise NotImplementedError("Phase 1: robots.txt 取得・判定を実装する")

    def fetch(self, path: str) -> str:
        """レート制限 + バックオフ + robots 尊重で 1 ページ取得（§8）。"""
        raise NotImplementedError("Phase 1: レート制限/バックオフ付き fetch を実装する")

    # --- 解析（サブクラスが実装）--------------------------------------------
    @abc.abstractmethod
    def parse(self, html: str, *, source_path: str) -> list[dict[str, Any]]:
        """取得した HTML を生レコードの list に変換する。"""
        raise NotImplementedError

    def run(self) -> list[dict[str, Any]]:
        """start_paths を巡回して生レコードを収集（§8 遵守機構経由）。"""
        raise NotImplementedError("Phase 1: 巡回ループを実装する")
