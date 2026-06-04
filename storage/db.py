"""DB エンジン・セッション・設定ロード（§3）。

- 本番 Postgres / ローカル SQLite を DATABASE_URL で切替（§10）。
- 秘密情報は .env のみ（§3）。pydantic-settings で読む。
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlmodel import Session, SQLModel, create_engine


class Settings(BaseSettings):
    """環境変数（§10）。.env から読む。"""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = Field(default="sqlite:///./jin.db", alias="DATABASE_URL")

    x402_facilitator_url: str = Field(default="", alias="X402_FACILITATOR_URL")
    x402_recipient_address: str = Field(default="", alias="X402_RECIPIENT_ADDRESS")
    x402_chain: str = Field(default="base", alias="X402_CHAIN")
    x402_asset: str = Field(default="usdc", alias="X402_ASSET")

    scraper_user_agent: str = Field(
        default="JapanInflationNowcastBot/0.1", alias="SCRAPER_USER_AGENT"
    )
    scraper_contact: str = Field(default="ops@example.com", alias="SCRAPER_CONTACT")

    # e-Stat（政府統計 API）の appId。運用者の環境にのみ入れる（このサンドボックスでは未設定）。
    estat_app_id: str = Field(default="", alias="ESTAT_APP_ID")

    base_date: date = Field(default=date(2025, 1, 1), alias="BASE_DATE")
    rebase_policy: str = Field(default="annual", alias="REBASE_POLICY")


@lru_cache
def get_settings() -> Settings:
    """設定のシングルトン。"""
    return Settings()


@lru_cache
def get_engine():
    """SQLAlchemy エンジンのシングルトン。"""
    url = get_settings().database_url
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, echo=False, connect_args=connect_args)


def init_db() -> None:
    """全テーブルを作成（冪等）。models を import して metadata に登録する。"""
    from storage import models  # noqa: F401  テーブル登録のため必須

    SQLModel.metadata.create_all(get_engine())


@contextmanager
def get_session() -> Iterator[Session]:
    """セッションのコンテキストマネージャ。"""
    with Session(get_engine()) as session:
        yield session
