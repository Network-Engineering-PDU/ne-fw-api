"""OTA periodic check daemon."""

import logging
import os
import signal
import sys
import time

from ttne import utils
from ttne.config import config

from . import config as ota_config
from .updater import run_check

logger = logging.getLogger(__name__)

PID_FILE = os.path.join(config.TTNE_DIR, "ota", "ttne-ota.pid")
_running = True


def _handle_signal(signum, _frame):
    global _running
    logger.info("OTA daemon received signal %s", signum)
    _running = False


def _sleep_until_due(interval: int, enabled: bool) -> None:
    """Sleep in short slices so runtime setting changes take effect promptly."""
    slept = 0
    while _running and slept < interval:
        sleep_seconds = min(5, interval - slept)
        time.sleep(sleep_seconds)
        slept += sleep_seconds

        cfg = ota_config.load_config()
        new_enabled = bool(cfg.get("enabled", True))
        interval = ota_config.check_interval_seconds(cfg)
        if not enabled and new_enabled:
            return
        enabled = new_enabled


def run_loop() -> None:
    global _running
    utils.config_logger()
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    logger.info("OTA daemon started")
    while _running:
        cfg = ota_config.load_config()
        interval = ota_config.check_interval_seconds(cfg)
        if cfg.get("enabled", True):
            try:
                run_check()
            except Exception:
                logger.exception("Unhandled OTA check error")
        else:
            logger.debug("OTA checks disabled, sleeping %ss", interval)

        _sleep_until_due(interval, bool(cfg.get("enabled", True)))

    logger.info("OTA daemon stopped")


def main():
    if len(sys.argv) < 2:
        print("Usage: ttne-ota {start|check-once|stop}")
        sys.exit(1)

    command = sys.argv[1]
    if command == "check-once":
        utils.config_logger()
        run_check()
        return

    if command == "start":
        from ttne.daemon import Daemon

        app = Daemon("ttne-ota", PID_FILE, run_loop)
        app.start()
        return

    if command == "stop":
        from ttne.daemon import Daemon

        app = Daemon("ttne-ota", PID_FILE, run_loop)
        app.stop()
        return

    print(f"Unknown command: {command}")
    sys.exit(1)
