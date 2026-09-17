"""公的CPIを国ごとに原子的に更新する。失敗時も古い値を最新と表示しない。"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import httpx

from scrapers.inflation import jp, kr, sg
from scrapers.inflation.common import empty_record

ADAPTERS = {"jp": jp.fetch, "kr": kr.fetch, "sg": sg.fetch}


def atomic_write(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, suffix=".tmp", delete=False
        ) as stream:
            temporary = Path(stream.name)
            json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def refresh(country: str, directory: Path, client: httpx.Client) -> bool:
    path = directory / f"{country}.json"
    attempt = datetime.now(UTC).isoformat()
    try:
        result = ADAPTERS[country](client)
        result["last_attempt_at"] = attempt
    except Exception as exc:
        # 公開ファイルにはエラー本文・認証情報を出さず固定コードだけを保存する。
        result = json.loads(path.read_text()) if path.exists() else empty_record(country)
        result.update(
            status="refresh_failed",
            stale=True,
            stale_reasons=["refresh_failed"],
            last_attempt_at=attempt,
            last_error="upstream_or_configuration_error",
        )
        atomic_write(path, result)
        print(
            f"{country}: 取得失敗（{type(exc).__name__}）。設定・公式仕様を確認してください。",
            file=sys.stderr,
        )
        return False
    atomic_write(path, result)
    print(f"{country}: 保存しました（対象月 {result['as_of']}）")
    return True


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="公的CPIの配信用JSONを更新します")
    parser.add_argument("--country", choices=["all", *ADAPTERS], default="all")
    parser.add_argument("--output-dir", type=Path, default=Path("data/inflation"))
    args = parser.parse_args(argv)
    countries = list(ADAPTERS) if args.country == "all" else [args.country]
    # 同じ出力先への同時更新は拒否。プロセス強制終了時のロック解除は運用者が確認する。
    args.output_dir.mkdir(parents=True, exist_ok=True)
    lock = args.output_dir / ".refresh.lock"
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        print("更新処理が実行中、または前回のロックが残っています。", file=sys.stderr)
        return 1
    try:
        with httpx.Client(
            timeout=30, headers={"User-Agent": "JIN-inflation/1.0", "Accept": "application/json"}
        ) as client:
            results = [refresh(country, args.output_dir, client) for country in countries]
        return 0 if all(results) else 1
    finally:
        os.close(descriptor)
        lock.unlink()


if __name__ == "__main__":
    raise SystemExit(main())
