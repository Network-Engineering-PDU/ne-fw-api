"""Boot success marker used by systemd after services start."""

import os
import sys

from . import state

BOOT_MARKER = os.path.join(state.OTA_DIR, "boot_success")
PENDING_VERSION_FILE = os.path.join(state.OTA_DIR, "pending_version")


def mark_success() -> None:
    os.makedirs(state.OTA_DIR, exist_ok=True)
    with open(BOOT_MARKER, "w", encoding="utf-8") as fh:
        fh.write("ok\n")
    state.clear_pending_update()


def main():
    if len(sys.argv) < 2 or sys.argv[1] != "mark-success":
        print("Usage: python -m ttne.ota.boot_health mark-success")
        sys.exit(1)
    mark_success()


if __name__ == "__main__":
    main()
