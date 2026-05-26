"""Configuration loader for apple-reminders-zectrix-sync."""
import logging
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


class Config:
    def __init__(self, config_path: str | Path | None = None,
                 zectrix_api_key: str | None = None,
                 zectrix_device_id: str | None = None,
                 poll_interval: int = 300,
                 db_path: str = "/data/sync.db",
                 zectrix_base_url: str = "https://cloud.zectrix.com"):
        self.zectrix_api_key = zectrix_api_key or ""
        self.zectrix_device_id = zectrix_device_id or ""
        self.zectrix_base_url = zectrix_base_url
        self.poll_interval = poll_interval
        self.db_path = Path(db_path)

        if config_path:
            self._load_from_file(Path(config_path))

        self._validate()

    def _load_from_file(self, path: Path):
        if not path.exists():
            logger.warning("Config file not found: %s", path)
            return
        with open(path) as f:
            raw = yaml.safe_load(f)
        cfg = raw.get("config", []) if isinstance(raw, dict) else raw
        if not isinstance(cfg, list):
            cfg = [cfg]
        for item in cfg:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            value = item.get("default") or item.get("value")
            if name == "zectrix_api_key":
                self.zectrix_api_key = str(value)
            elif name == "zectrix_device_id":
                self.zectrix_device_id = str(value)
            elif name == "zectrix_base_url":
                self.zectrix_base_url = str(value)
            elif name == "poll_interval":
                self.poll_interval = int(value)
            elif name == "db_path":
                self.db_path = Path(str(value))

    def _validate(self):
        if not self.zectrix_api_key:
            raise ValueError("zectrix_api_key is required")
        if not self.zectrix_device_id:
            raise ValueError("zectrix_device_id is required")