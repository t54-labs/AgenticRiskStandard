"""HTTP transport layer for ARS client SDK."""

from __future__ import annotations

import httpx


class ARSClientError(Exception):
    """Error from the ARS server."""

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"HTTP {status_code}: {detail}")


class Transport:
    """Thin wrapper around httpx.Client for ARS server communication."""

    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        timeout: float = 30.0,
        client: httpx.Client | None = None,
    ) -> None:
        self._client = client or httpx.Client(base_url=base_url, timeout=timeout)

    def post(self, path: str, json: dict) -> dict:
        resp = self._client.post(path, json=json)
        if resp.status_code >= 400:
            detail = ""
            try:
                detail = resp.json().get("detail", resp.text)
            except Exception:
                detail = resp.text
            raise ARSClientError(resp.status_code, detail)
        return resp.json()

    def get(self, path: str) -> dict:
        resp = self._client.get(path)
        if resp.status_code >= 400:
            detail = ""
            try:
                detail = resp.json().get("detail", resp.text)
            except Exception:
                detail = resp.text
            raise ARSClientError(resp.status_code, detail)
        return resp.json()

    def close(self) -> None:
        self._client.close()
