"""CLI entry point for apple-reminders-zectrix-sync."""
import argparse
import logging
import sys
import time

from .config import Config
from .sync_engine import SyncDB, SyncEngine
from .adapters.apple_reminders import AppleRemindersAdapter
from .adapters.zectrix import ZectrixAdapter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def run_sync(cfg: Config, dry_run: bool = False):
    db = SyncDB(cfg.db_path)
    apple = AppleRemindersAdapter()
    zectrix = ZectrixAdapter(cfg.zectrix_api_key, cfg.zectrix_device_id, cfg.zectrix_base_url)
    engine = SyncEngine(db, apple, zectrix, dry_run=dry_run)

    logger.info("=== Sync start ===")
    delta = engine.sync()
    if delta.has_changes:
        logger.info("Changes: apple_created=%d, zectrix_created=%d, "
                    "apple_deleted=%d, zectrix_deleted=%d",
                    len(delta.apple_created), len(delta.zectrix_created),
                    len(delta.apple_deleted), len(delta.zectrix_deleted))
    else:
        logger.info("No changes.")
    logger.info("=== Sync done ===")
    return delta


def main():
    parser = argparse.ArgumentParser(description="Apple Reminders <-> Zectrix sync")
    parser.add_argument("--config", "-c", help="Path to config.yaml")
    parser.add_argument("--dry-run", "-n", action="store_true", help="Preview without changes")
    parser.add_argument("--daemon", "-d", action="store_true", help="Run in polling daemon mode")
    parser.add_argument("--interval", type=int, default=300,
                        help="Poll interval in seconds (daemon mode)")
    args = parser.parse_args()

    try:
        cfg = Config(config_path=args.config)
    except Exception as e:
        logger.error("Config error: %s", e)
        sys.exit(1)

    if args.daemon:
        logger.info("Daemon mode started, polling every %ds", args.interval)
        while True:
            try:
                run_sync(cfg, dry_run=args.dry_run)
            except Exception as e:
                logger.error("Sync error: %s", e)
            time.sleep(args.interval)
    else:
        run_sync(cfg, dry_run=args.dry_run)


if __name__ == "__main__":
    main()