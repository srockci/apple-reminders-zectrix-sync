"""Zectrix cloud API adapter."""
import logging
from typing import Any

import requests

logger = logging.getLogger(__name__)


class ZectrixAdapter:
    def __init__(self, api_key: str, device_id: str,
                 base_url: str = "https://cloud.zectrix.com"):
        self.api_key = api_key
        self.device_id = device_id
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers = {
            "X-API-Key": api_key,
            "Content-Type": "application/json",
        }

    def _request(self, method: str, path: str, **kwargs) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        resp = self.session.request(method, url, timeout=15, **kwargs)
        payload = resp.json()
        if payload.get("code") != 0:
            raise RuntimeError(f"Zectrix API error {payload.get('code')}: {payload.get('msg')}")
        return payload

    def list_todos(self) -> list[dict[str, Any]]:
        """List all todos for the device."""
        return self._request("GET", "/open/v1/todos").get("data", [])

    def create_todo(self, title: str,
                    due_date: str | None = None,
                    due_time: str | None = None,
                    priority: int = 0) -> dict[str, Any]:
        data: dict[str, Any] = {"title": title, "deviceId": self.device_id}
        if due_date:
            data["dueDate"] = due_date
        if due_time:
            data["dueTime"] = due_time
        if priority:
            data["priority"] = priority
        return self._request("POST", "/open/v1/todos", json=data).get("data", {})

    def complete_todo(self, todo_id: int) -> dict[str, Any]:
        return self._request("PUT", f"/open/v1/todos/{todo_id}/complete").get("data", {})

    def delete_todo(self, todo_id: int) -> dict[str, Any]:
        return self._request("DELETE", f"/open/v1/todos/{todo_id}").get("data", {})

    def push_text(self, text: str, page_id: str = "1") -> dict[str, Any]:
        return self._request(
            "POST", "/open/v1/devices/push",
            json={"deviceId": self.device_id, "text": text, "pageId": page_id}
        ).get("data", {})