"""Tiny Python client for calling any registered MeteorBase service."""
from __future__ import annotations

import os
from typing import Any

import requests


class MeteorBase:
    def __init__(self, api_key: str | None = None, base_url: str | None = None, timeout: int = 15):
        self.base_url = (base_url or os.environ.get("METEORBASE_URL", "https://tinyapi-urjr.onrender.com")).rstrip("/")
        self.api_key = api_key or os.environ["MB_API_KEY"]
        self.timeout = timeout

    def request(self, method: str, service: str, path: str, **kwargs: Any) -> requests.Response:
        headers = dict(kwargs.pop("headers", {}) or {})
        headers["X-API-Key"] = self.api_key
        headers.setdefault("Accept", "application/json")
        return requests.request(
            method=method,
            url=f"{self.base_url}/api/v1/{service.strip('/')}/{path.lstrip('/')}",
            headers=headers,
            timeout=self.timeout,
            **kwargs,
        )

    def get(self, service: str, path: str, **kwargs: Any) -> requests.Response:
        return self.request("GET", service, path, **kwargs)

    def post(self, service: str, path: str, **kwargs: Any) -> requests.Response:
        return self.request("POST", service, path, **kwargs)

    def put(self, service: str, path: str, **kwargs: Any) -> requests.Response:
        return self.request("PUT", service, path, **kwargs)

    def patch(self, service: str, path: str, **kwargs: Any) -> requests.Response:
        return self.request("PATCH", service, path, **kwargs)

    def delete(self, service: str, path: str, **kwargs: Any) -> requests.Response:
        return self.request("DELETE", service, path, **kwargs)


if __name__ == "__main__":
    client = MeteorBase()
    response = client.get("oblivion", "/sessions")
    response.raise_for_status()
    print(response.json())
