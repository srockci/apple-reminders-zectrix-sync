"""Textual TUI for Zectrix Sync."""
from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path
from typing import Optional

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    Log,
    ProgressBar,
    Static,
    Switch,
    TabbedContent,
    TabPane,
)


class ConfigState:
    def __init__(self):
        self.api_key: str = ""
        self.device_id: str = ""
        self.device_name: str = ""
        self.poll_interval: int = 300
        self.daemon_mode: bool = False
        self.db_path: str = ""
        self.config_loaded: bool = False

    def load_from_file(self, path: Path):
        import yaml
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        self.api_key = data.get("zectrix_api_key", "")
        self.device_id = data.get("zectrix_device_id", "")
        self.poll_interval = data.get("poll_interval", 300)
        self.db_path = data.get("db_path", str(Path(__file__).parent / "sync.db"))
        self.config_loaded = bool(self.api_key)


class ZectrixAPI:
    def __init__(self, api_key: str, base_url: str = "https://cloud.zectrix.com"):
        self.api_key = api_key
        self.base_url = base_url

    def _headers(self):
        return {"X-API-Key": self.api_key}

    def list_devices(self) -> list[dict]:
        import requests
        resp = requests.get(
            f"{self.base_url}/api/device/list",
            headers=self._headers(), timeout=10
        )
        resp.raise_for_status()
        return resp.json().get("data", [])

    def list_todos(self, device_id: str) -> list[dict]:
        import requests
        resp = requests.get(
            f"{self.base_url}/api/todo/list",
            headers=self._headers(),
            params={"deviceId": device_id},
            timeout=10
        )
        resp.raise_for_status()
        return resp.json().get("data", [])

    def test_connection(self) -> bool:
        import requests
        resp = requests.get(
            f"{self.base_url}/api/device/list",
            headers=self._headers(), timeout=10
        )
        return resp.status_code == 200


class SyncWorker(threading.Thread):
    def __init__(self, config: ConfigState, log_callback):
        super().__init__(daemon=True)
        self.config = config
        self.log_callback = log_callback
        self.stop_event = threading.Event()

    def run(self):
        from app.sync_engine import SyncDB, SyncEngine
        from app.adapters.apple_reminders import AppleRemindersAdapter
        from app.adapters.zectrix import ZectrixAdapter

        api = ZectrixAPI(self.config.api_key)
        zectrix = ZectrixAdapter(
            api_key=self.config.api_key,
            device_id=self.config.device_id,
        )
        apple = AppleRemindersAdapter()
        db = SyncDB(Path(self.config.db_path))
        engine = SyncEngine(db, apple, zectrix)

        while not self.stop_event.wait(self.config.poll_interval):
            self.log_callback("syncing...")
            try:
                delta = engine.sync()
                self.log_callback(f"done: {delta.apple_created} created")
            except Exception as e:
                self.log_callback(f"error: {e}")


class ZectrixSyncApp(App):
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("s", "sync_now", "Sync Now"),
    ]

    api_key = reactive("")
    device_id = reactive("")
    device_name = reactive("")
    poll_interval = reactive(300)
    daemon_mode = reactive(False)
    db_path = reactive("")
    syncing = reactive(False)
    log_lines: list[str] = reactive([])

    CSS = """
    Screen {
        background: #1a1a2e;
    }
    TabbedContent {
        dock: top;
    }
    TabPane {
        padding: 1 2;
    }
    #form-grid {
        layout: grid;
        grid-size: 2;
        grid-gutter: 2;
        padding: 1;
    }
    .field-label {
        color: #a0a0c0;
        width: 14;
    }
    Input {
        width: 100%;
    }
    #log-area {
        height: 1fr;
        border: solid #e94560;
        padding: 1;
    }
    #status-bar {
        dock: bottom;
        height: 1;
        background: #16213e;
        color: #a0a0c0;
        padding: 0 2;
    }
    Button {
        margin: 0 1;
    }
    .button-row {
        height: auto;
        padding: 1 0;
    }
    """

    def __init__(self):
        super().__init__()
        self.config = ConfigState()
        self.worker: Optional[SyncWorker] = None

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent():
            with TabPane("Setup", id="setup"):
                with Vertical(id="form-grid"):
                    yield Label("API Key:", classes="field-label")
                    yield Input(placeholder="zt_xxxxxxxx", id="apikey-input", password=True)
                    yield Label("Device ID:", classes="field-label")
                    yield Input(placeholder="20:6E:F1:...", id="device-input")
                    yield Label("Poll Interval (s):", classes="field-label")
                    yield Input(placeholder="300", id="interval-input")
                    yield Label("DB Path:", classes="field-label")
                    yield Input(placeholder="sync.db", id="db-input")
                yield Horizontal(
                    Button("Load Config", id="btn-load", variant="primary"),
                    Button("Save Config", id="btn-save"),
                    Button("Test Connection", id="btn-test"),
                    id="button-row-1",
                )
                yield Horizontal(
                    Button("Get Devices", id="btn-devices"),
                    Button("Start Sync", id="btn-start", variant="success"),
                    Button("Stop Sync", id="btn-stop", variant="error"),
                    id="button-row-2",
                )

            with TabPane("Log", id="log"):
                yield Log(id="log-area", auto_scroll=True)

    def on_mount(self) -> None:
        self.title = "Zectrix Sync"
        # Set defaults
        db_default = str(Path(__file__).parent / "sync.db")
        self.query_one("#db-input", Input).value = db_default
        self.query_one("#interval-input", Input).value = "300"

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        if btn_id == "btn-load":
            self._load_config()
        elif btn_id == "btn-save":
            self._save_config()
        elif btn_id == "btn-test":
            self._test_connection()
        elif btn_id == "btn-devices":
            self._get_devices()
        elif btn_id == "btn-start":
            self._start_sync()
        elif btn_id == "btn-stop":
            self._stop_sync()

    def _read_inputs(self):
        self.api_key = self.query_one("#apikey-input", Input).value.strip()
        self.device_id = self.query_one("#device-input", Input).value.strip()
        self.poll_interval = int(self.query_one("#interval-input", Input).value.strip() or "300")
        self.db_path = self.query_one("#db-input", Input).value.strip()

    def _log(self, msg: str):
        log = self.query_one("#log-area", Log)
        log.write_line(msg)

    def _load_config(self):
        from app.config import Config
        self._read_inputs()
        cfg_path = Path(__file__).parent.parent / "config.yaml"
        if cfg_path.exists():
            self.config.load_from_file(cfg_path)
            self.query_one("#apikey-input", Input).value = self.config.api_key
            self.query_one("#device-input", Input).value = self.config.device_id
            self.query_one("#interval-input", Input).value = str(self.config.poll_interval)
            self.query_one("#db-input", Input).value = self.config.db_path
            self._log(f"Loaded: {cfg_path}")
        else:
            self._log(f"Config not found: {cfg_path}")

    def _save_config(self):
        import yaml
        self._read_inputs()
        cfg_path = Path(__file__).parent.parent / "config.yaml"
        data = {
            "zectrix_api_key": self.api_key,
            "zectrix_device_id": self.device_id,
            "poll_interval": self.poll_interval,
            "db_path": self.db_path,
        }
        with open(cfg_path, "w") as f:
            yaml.dump(data, f)
        self._log(f"Saved: {cfg_path}")

    def _test_connection(self):
        self._read_inputs()
        if not self.api_key:
            self._log("Error: API key required")
            return
        try:
            api = ZectrixAPI(self.api_key)
            api.test_connection()
            self._log("Connection OK!")
        except Exception as e:
            self._log(f"Connection failed: {e}")

    def _get_devices(self):
        self._read_inputs()
        if not self.api_key:
            self._log("Error: API key required")
            return
        try:
            api = ZectrixAPI(self.api_key)
            devices = api.list_devices()
            for d in devices:
                self._log(f"  {d.get('id','?')} - {d.get('name','?')}")
        except Exception as e:
            self._log(f"Failed: {e}")

    def _start_sync(self):
        self._read_inputs()
        if not self.api_key or not self.device_id:
            self._log("Error: API key and Device ID required")
            return
        if self.worker and self.worker.is_alive():
            self._log("Already running")
            return
        self.config.api_key = self.api_key
        self.config.device_id = self.device_id
        self.config.poll_interval = self.poll_interval
        self.config.db_path = self.db_path or str(Path(__file__).parent / "sync.db")
        self.worker = SyncWorker(self.config, self._log)
        self.worker.start()
        self._log(f"Started (poll={self.poll_interval}s)")

    def _stop_sync(self):
        if self.worker:
            self.worker.stop_event.set()
            self._log("Stopping...")
        else:
            self._log("Not running")


if __name__ == "__main__":
    app = ZectrixSyncApp()
    app.run()
