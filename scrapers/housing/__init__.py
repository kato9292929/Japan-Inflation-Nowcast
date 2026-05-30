"""住居ソースアダプタ（プラグイン）。

対象サイトは運用者が config/sources.yaml に記入し、対応するアダプタをここに置く
（例: scrapers/housing/<source_id>.py）。各ファイル冒頭に §8 の遵守注意を明記すること。
既定では何も取得しない（sources.yaml の housing が空）。
"""
