"""抽象スクレイパアダプタと遵守機構（§8 ハード制約）。

このモジュールが内蔵する遵守機構:
- robots.txt の取得・尊重（不許可パスは取得しない）。
- レート制限（1 req / 数秒）+ 指数バックオフ + 同時実行 1。
- User-Agent / 問い合わせ先の明示。
- ``config/sources.yaml`` が空なら何も取得しない安全既定。

重要（§8）: 各ソースの利用規約・著作権・関連法の遵守は運用者責任である。
コード側は法的判断をしない。生データは内部保存のみで再配布しない。

テスト容易性: ネットワーク部（httpx クライアント）と待機（sleeper）は注入可能。
実通信なしでフィクスチャ検証できる。
"""

from __future__ import annotations

import abc
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urljoin
from urllib.robotparser import RobotFileParser

import httpx
import yaml

logger = logging.getLogger(__name__)

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
SOURCES_PATH = CONFIG_DIR / "sources.yaml"

# リトライ対象の HTTP ステータス（429 + 5xx）。
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
# robots.txt が「存在しない」ことを示すステータス（標準的に全許可扱い）。
_ROBOTS_ABSENT_STATUS = {404, 410}


class DisallowedPathError(Exception):
    """robots.txt により取得が許可されていないパスを fetch しようとした（§8）。"""


@dataclass(frozen=True)
class SourceConfig:
    """1 ソースの設定（config/sources.yaml の 1 エントリ）。

    type='scrape'（既定, HTTP スクレイピング）/ 'csv'（ローカル CSV 取り込み）。
    csv の場合は path（CSV パス）と column_map（CSV 列名 -> raw フィールド名）を使う。
    """

    id: str
    base_url: str = ""
    enabled: bool = False
    type: str = "scrape"
    path: str | None = None
    column_map: dict[str, str] = field(default_factory=dict)
    rate_limit_seconds: float = 5.0
    max_concurrency: int = 1
    respect_robots: bool = True
    start_paths: list[str] = field(default_factory=list)


def load_sources(kind: str, path: Path = SOURCES_PATH) -> list[SourceConfig]:
    """``config/sources.yaml`` から指定種別（'housing' / 'food'）のソースを読む。

    安全既定（§8）: ファイルが無い / 空 / 当該種別が無い場合は空リストを返す
    （= 何も取得しない）。enabled=False のソースも除外する。
    type='csv' のソースは path / column_map を読み取る。
    """
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries = data.get(kind) or []
    sources: list[SourceConfig] = []
    for entry in entries:
        cfg = SourceConfig(
            id=entry["id"],
            base_url=entry.get("base_url", ""),
            enabled=bool(entry.get("enabled", False)),
            type=str(entry.get("type", "scrape")),
            path=entry.get("path"),
            column_map=dict(entry.get("column_map") or {}),
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

    Args:
        config: ソース設定。
        user_agent: 明示する User-Agent（§8）。
        contact: 問い合わせ先（§8）。UA に併記する。
        client: 注入用 httpx クライアント。未指定なら遅延生成する（テストで差し替え可）。
        sleeper: スロットル/バックオフの待機関数（既定 time.sleep。テストで差し替え可）。
        clock: 経過時間計測の関数（既定 time.monotonic。テストで差し替え可）。
        max_retries: 429/5xx に対する最大リトライ回数。
    """

    kind: str = "base"

    def __init__(
        self,
        config: SourceConfig,
        *,
        user_agent: str,
        contact: str,
        client: httpx.Client | None = None,
        sleeper: Callable[[float], None] | None = None,
        clock: Callable[[], float] | None = None,
        max_retries: int = 4,
    ) -> None:
        self.config = config
        self.user_agent = user_agent
        self.contact = contact
        self.max_retries = max_retries

        self._client = client
        self._owns_client = client is None
        self._sleeper = sleeper or time.sleep
        self._clock = clock or time.monotonic

        # robots パーサのキャッシュ（base_url -> RobotFileParser | None）。
        # None は「robots 取得に失敗 = 安全側で不許可」を表す。
        self._robots_cache: dict[str, RobotFileParser | None] = {}
        self._last_request_at: float | None = None

    # --- クライアント --------------------------------------------------------
    def _ua_string(self) -> str:
        """User-Agent 文字列（§8: UA と問い合わせ先を明示）。"""
        return f"{self.user_agent} (+contact: {self.contact})"

    @property
    def client(self) -> httpx.Client:
        """httpx クライアント（注入が無ければ遅延生成）。"""
        if self._client is None:
            self._client = httpx.Client(
                headers={"User-Agent": self._ua_string()},
                timeout=30.0,
                follow_redirects=True,
            )
            self._owns_client = True
        return self._client

    def close(self) -> None:
        """自前生成したクライアントを閉じる（注入クライアントは閉じない）。"""
        if self._client is not None and self._owns_client:
            self._client.close()
            self._client = None

    def _url(self, path: str) -> str:
        """base_url と path を結合した絶対 URL。"""
        return urljoin(self.config.base_url, path)

    # --- robots.txt（§8）----------------------------------------------------
    def _robots(self) -> RobotFileParser | None:
        """この base_url の robots パーサを取得（キャッシュ）。失敗時は None。"""
        base = self.config.base_url
        if base in self._robots_cache:
            return self._robots_cache[base]

        robots_url = urljoin(base, "/robots.txt")
        parser: RobotFileParser | None
        try:
            resp = self.client.get(robots_url)
            status = resp.status_code
            if status == 200:
                parser = RobotFileParser()
                parser.parse(resp.text.splitlines())
            elif status in _ROBOTS_ABSENT_STATUS:
                # robots.txt が無い = 全許可（標準挙動）。
                parser = RobotFileParser()
                parser.parse([])
            else:
                # 取得できたが想定外ステータス。安全側で不許可。
                logger.warning(
                    "robots.txt %s returned status %s; treating as disallow", robots_url, status
                )
                parser = None
        except Exception as exc:  # noqa: BLE001  ネットワーク失敗は安全側に倒す
            logger.warning(
                "robots.txt fetch failed for %s: %s; treating as disallow", robots_url, exc
            )
            parser = None

        self._robots_cache[base] = parser
        return parser

    def is_allowed(self, path: str) -> bool:
        """robots.txt に基づき path 取得可否を判定（§8）。

        - respect_robots=False なら運用者が明示的に無効化した扱いで True。
        - robots 取得失敗時は安全側で False。
        """
        if not self.config.respect_robots:
            return True
        parser = self._robots()
        if parser is None:
            return False
        return parser.can_fetch(self.user_agent, self._url(path))

    # --- 取得（§8: スロットル + バックオフ + robots 尊重）---------------------
    def _throttle(self) -> None:
        """連続リクエスト間に rate_limit_seconds を確保する（同時実行 1 前提の直列）。"""
        if self._last_request_at is not None:
            elapsed = self._clock() - self._last_request_at
            wait = self.config.rate_limit_seconds - elapsed
            if wait > 0:
                self._sleeper(wait)
        self._last_request_at = self._clock()

    def fetch(self, path: str) -> str:
        """レート制限 + バックオフ + robots 尊重で 1 ページ取得（§8）。

        Raises:
            DisallowedPathError: robots.txt が当該パスを許可しない場合（取得しない）。
            httpx.HTTPStatusError: リトライ上限後も成功しなかった場合。
        """
        if not self.is_allowed(path):
            raise DisallowedPathError(f"robots.txt disallows: {path}")

        url = self._url(path)
        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            self._throttle()
            try:
                resp = self.client.get(url)
            except httpx.RequestError as exc:
                # ネットワーク系エラーはリトライ対象。
                last_exc = exc
                if attempt < self.max_retries:
                    self._backoff(attempt)
                    continue
                raise

            if resp.status_code in _RETRYABLE_STATUS:
                if attempt < self.max_retries:
                    logger.warning(
                        "fetch %s -> %s; retrying (attempt %s)",
                        url,
                        resp.status_code,
                        attempt + 1,
                    )
                    self._backoff(attempt)
                    continue
                resp.raise_for_status()
            # 2xx 以外（かつ非リトライ）はここで例外化。2xx は本文を返す。
            resp.raise_for_status()
            return resp.text

        # ここには来ない想定（ループ内で return / raise する）。保険。
        assert last_exc is not None
        raise last_exc

    def _backoff(self, attempt: int) -> None:
        """指数バックオフ（2^attempt 秒）。"""
        self._sleeper(2.0 ** attempt)

    # --- 解析（サブクラスが実装）--------------------------------------------
    @abc.abstractmethod
    def parse(self, html: str, *, source_path: str) -> list[dict[str, Any]]:
        """取得した HTML を生レコードの list に変換する。"""
        raise NotImplementedError

    def run(self) -> list[dict[str, Any]]:
        """start_paths を巡回して生レコードを収集（§8 遵守機構経由）。

        1 ページの失敗（robots 不許可・HTTP エラー・解析エラー）で全体を落とさず、
        log して次のページに進む。
        """
        records: list[dict[str, Any]] = []
        try:
            for path in self.config.start_paths:
                try:
                    html = self.fetch(path)
                    page_records = self.parse(html, source_path=path)
                    records.extend(page_records)
                except Exception as exc:  # noqa: BLE001  1 ページ失敗で全体を止めない
                    logger.warning("skip path %s for source %s: %s", path, self.config.id, exc)
                    continue
        finally:
            self.close()
        return records
