"""日次ジョブ（§3, §9 Phase 7）。

単一エントリポイント。cron から叩く。流れ:
    scrape -> etl -> index -> composite -> validate

すべて冪等（同日再実行で二重計上しない, §3）。部分復旧できる構成にする（Phase 7）。
``config/sources.yaml`` が空なら scrape 段は何も取得しない安全既定（§8）。
"""

from __future__ import annotations

import argparse
from datetime import date


def run(*, as_of: date | None = None) -> int:
    """全段を順に実行する。Returns: プロセス終了コード（0=成功）。"""
    raise NotImplementedError("Phase 7: scrape→etl→index→composite→validate を実装する")


def main() -> int:
    """CLI エントリポイント（pyproject の jin-daily）。"""
    parser = argparse.ArgumentParser(description="Japan Inflation Nowcast daily job")
    parser.add_argument("--date", type=date.fromisoformat, default=None, help="対象日 (ISO)")
    args = parser.parse_args()
    return run(as_of=args.date)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
