"""OTA periodic check daemon."""

import logging
import os
import signal
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from ttne import utils
from ttne.config import config

from . import config as ota_config
from . import state as ota_state
from .updater import RETRY_SECONDS, run_check

logger = logging.getLogger(__name__)

PID_FILE = os.path.join(config.TTNE_DIR, "ota", "ttne-ota.pid")
# How often the daemon looks whether a check is due
POLL_SECONDS = 60
_running = True


def _handle_signal(signum, _frame):
    global _running
    logger.info("OTA daemon received signal %s", signum)
    _running = False


def _parse_time(text: str) -> Optional[float]:
    try:
        return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc).timestamp()
    except (TypeError, ValueError):
        return None


def check_due(cfg: Dict[str, Any], state: Dict[str, Any], now: float,
        since_attempt: Optional[float]) -> bool:
    """Whether the periodic check is due.

    The interval counts from the last completed check (saved, so a restart
    or reboot doesn't check again early); a failed or skipped check (no
    internet, server down) is retried after RETRY_SECONDS.

    since_attempt: seconds since this daemon last checked, None before its
    first check.
    """
    if not cfg.get("enabled", True):
        return False
    if since_attempt is not None and since_attempt < RETRY_SECONDS:
        return False
    last = _parse_time(state.get("last_check_time", ""))
    if last is None or last > now:
        # Never checked, or the clock went back (no clock battery)
        return True
    interval = ota_config.check_interval_seconds(cfg)
    if state.get("status") == "failed" or state.get("last_error"):
        interval = min(interval, RETRY_SECONDS)
    return now - last >= interval


def run_loop() -> None:
    global _running
    utils.config_logger()
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    logger.info("OTA daemon started")
    last_attempt = None
    while _running:
        # Settings changed on the display or web UI apply within a minute.
        cfg = ota_config.load_config()
        since_attempt = (None if last_attempt is None
                         else time.monotonic() - last_attempt)
        if check_due(cfg, ota_state.load_state(), time.time(), since_attempt):
            last_attempt = time.monotonic()
            try:
                run_check()
            except Exception:
                logger.exception("Unhandled OTA check error")

        slept = 0
        while _running and slept < POLL_SECONDS:
            time.sleep(5)
            slept += 5

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
