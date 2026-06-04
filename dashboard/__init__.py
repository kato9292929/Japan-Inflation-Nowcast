"""無償 headline ダッシュボード（読み取り専用, §1, §8 Phase 8）。

API の無償エンドポイントを叩いて JP-INFL-NOWCAST の headline を表示する。
描画ロジックは render.py の純粋関数。live 配信は運用者環境で行う。
"""

from dashboard.render import build_headline_view, coverage_label, render_html

__all__ = ["build_headline_view", "coverage_label", "render_html"]
