"""e-Stat（政府統計の総合窓口）統計データ API クライアント（§8）。

実通信はこのサンドボックスからは行えない（api.e-stat.go.jp へ出られない）。本クライアントは
HTTP クライアントを注入可能にしてテストでモックする。live は運用者の環境で appId
（ESTAT_APP_ID）を入れて実行する前提。

法務（§8）: e-Stat の利用規約・出典表示・関連法の遵守は運用者責任。取得した生データは
内部保存のみ・再配布しない。公開するのは派生集計（指数・統計）だけ。
"""

from __future__ import annotations

from typing import Any

import httpx

# getStatsData の JSON エンドポイント（API v3.0）。
DEFAULT_BASE_URL = "https://api.e-stat.go.jp/rest/3.0/app/json"


class EStatError(Exception):
    """e-Stat API のエラー（appId 未設定・通信失敗・API ステータス異常）。"""


class EStatClient:
    """e-Stat 統計データ API の薄いクライアント。HTTP クライアント注入可（テスト用）。"""

    def __init__(
        self,
        app_id: str,
        *,
        client: httpx.Client | None = None,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 30.0,
    ) -> None:
        self.app_id = app_id
        self.base_url = base_url.rstrip("/")
        self._client = client
        self._owns_client = client is None
        self._timeout = timeout

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=self._timeout)
            self._owns_client = True
        return self._client

    def close(self) -> None:
        if self._client is not None and self._owns_client:
            self._client.close()
            self._client = None

    def get_stats_data(self, stats_data_id: str, **params: Any) -> dict[str, Any]:
        """getStatsData を呼び、JSON を返す。

        Raises:
            EStatError: appId 未設定 / 通信失敗 / API ステータス != 0。
        """
        if not self.app_id:
            raise EStatError("ESTAT_APP_ID が未設定です（運用者の環境で設定する）")

        query: dict[str, Any] = {"appId": self.app_id, "statsDataId": stats_data_id}
        query.update({k: v for k, v in params.items() if v is not None})
        try:
            resp = self.client.get(f"{self.base_url}/getStatsData", params=query)
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise EStatError(f"e-Stat getStatsData 失敗: {exc}") from exc

        result = (data.get("GET_STATS_DATA") or {}).get("RESULT") or {}
        status = result.get("STATUS")
        if status not in (0, "0"):
            raise EStatError(f"e-Stat API status={status}: {result.get('ERROR_MSG')}")
        return data


# --------------------------------------------------------------------------- #
# JSON パース・ヘルパ
# --------------------------------------------------------------------------- #
def _as_list(obj: Any) -> list[Any]:
    """e-Stat の JSON は単一要素を dict、複数を list で返すため正規化する。"""
    if obj is None:
        return []
    return obj if isinstance(obj, list) else [obj]


def extract_class_lookup(data: dict[str, Any]) -> dict[str, dict[str, str]]:
    """CLASS_INF から {class_id: {code: name}} のルックアップを作る。"""
    stat = (data.get("GET_STATS_DATA") or {}).get("STATISTICAL_DATA") or {}
    class_objs = _as_list((stat.get("CLASS_INF") or {}).get("CLASS_OBJ"))
    lookup: dict[str, dict[str, str]] = {}
    for obj in class_objs:
        cid = obj.get("@id")
        if cid is None:
            continue
        codes: dict[str, str] = {}
        for c in _as_list(obj.get("CLASS")):
            code = c.get("@code")
            if code is not None:
                codes[str(code)] = str(c.get("@name", code))
        lookup[str(cid)] = codes
    return lookup


def extract_values(data: dict[str, Any]) -> list[dict[str, Any]]:
    """DATA_INF.VALUE のリストを返す（各要素は @cat01/@area/@time/@unit/$ 等）。"""
    stat = (data.get("GET_STATS_DATA") or {}).get("STATISTICAL_DATA") or {}
    return _as_list((stat.get("DATA_INF") or {}).get("VALUE"))
