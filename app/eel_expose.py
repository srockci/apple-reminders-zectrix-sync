"""Eel exposed functions for the web UI."""
import json
import logging
import os
import sys
from pathlib import Path

import eel

from .config import Config
from .sync_engine import SyncDB, SyncEngine
from .adapters.apple_reminders import AppleRemindersAdapter
from .adapters.zectrix import ZectrixAdapter

logger = logging.getLogger(__name__)

# ── Config file in same directory as this module ──────────────────
_CONFIG_FILE = Path(__file__).parent.parent / "config.json"


# ── Eel helpers ────────────────────────────────────────────────────

def _load_json_config() -> dict:
    if not _CONFIG_FILE.exists():
        return {}
    with open(_CONFIG_FILE) as f:
        return json.load(f)


def _save_json_config(data: dict):
    with open(_CONFIG_FILE, "w") as f:
        json.dump(data, f, indent=2)


# ── Exposed functions ──────────────────────────────────────────────

@eel.expose
def test_api(api_key: str) -> dict:
    """Test API key and return device list."""
    try:
        zx = ZectrixAdapter(api_key, "dummy", "https://cloud.zectrix.com")
        # Try to list devices (GET /open/v1/devices or similar)
        # Zectrix API: GET /open/v1/devices returns device list
        resp = zx._request("GET", "/open/v1/devices")
        devices = resp.get("data", [])
        return {"ok": True, "devices": devices}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@eel.expose
def run_sync(api_key: str, cfg: dict) -> dict:
    """Run a single sync pass. Returns log lines + counts."""
    import io
    from contextlib import redirect_stderr, redirect_stdout

    # Capture log output
    log_lines = []
    class LogCapture(logging.Handler):
        def emit(record):
            log_lines.append(record.getMessage())

    handler = LogCapture()
    logging.getLogger().addHandler(handler)

    try:
        zectrix_device_id = (cfg.get("devices") or [""])[0] or "20:6E:F1:B4:81:AC"
        db_path = Path(cfg.get("db_path", "./sync.db"))

        db     = SyncDB(db_path)
        apple  = AppleRemindersAdapter()
        zx     = ZectrixAdapter(api_key, zectrix_device_id)

        dry_run = cfg.get("dry_run", False)
        engine  = SyncEngine(db, apple, zx, dry_run=dry_run)

        delta = engine.sync()

        result = {
            "log":           "\n".join(log_lines) or "No changes.",
            "apple_count":   len(delta.apple_created),
            "zectrix_count": len(delta.zectrix_created),
            "apple_deleted": len(delta.apple_deleted),
            "zectrix_deleted": len(delta.zectrix_deleted),
        }
    except Exception as e:
        result = {"log": f"Error: {e}", "apple_count": 0, "zectrix_count": 0}
    finally:
        logging.getLogger().removeHandler(handler)

    return result


@eel.expose
def save_config(api_key: str, cfg: dict):
    data = {
        "api_key":       api_key,
        "poll_interval": cfg.get("poll_interval", 300),
        "daemon":        bool(cfg.get("daemon")),
        "db_path":       cfg.get("db_path", "./sync.db"),
        "devices":       cfg.get("devices", []),
    }
    _save_json_config(data)


@eel.expose
def load_config() -> dict:
    return _load_json_config()


@eel.expose
def minimize_window():
    """Minimize the Eel window (close button → background daemon)."""
    # Eel doesn't directly support minimize; we just let the window close.
    # The calling code in app.js calls this on the close button.
    pass