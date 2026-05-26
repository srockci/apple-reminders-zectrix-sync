"""Main entry point — starts the Eel web UI."""
import logging
from pathlib import Path

import eel

from app.eel_expose import test_api, run_sync, save_config, load_config, minimize_window

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)

WEB_PATH = str(Path(__file__).parent / "web")


def main():
    eel.init(WEB_PATH)
    eel.start("index.html", size=(480, 700), resizable=False, close_callback=lambda x: None)


if __name__ == "__main__":
    main()