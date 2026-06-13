"""Persistent OTA state stored on the device."""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from ttne.config import Config

logger = logging.getLogger(__name__)

OTA_DIR = os.path.join(Config.TTNE_DIR, "ota")
OTA_STATE_FILE = os.path.join(OTA_DIR, "ota_state.json")
OTA_DOWNLOAD_DIR = os.path.join(OTA_DIR, "downloads")

STATUSES = (
    "idle",
    "checking",
    "downloading",
    "verifying",
    "installing",
    "pending_reboot",
    "failed",
    "success",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def default_state() -> Dict[str, Any]:
    return {
        "installed_version": Config.VERSION,
        "available_version": "",
        "last_check_time": "",
        "last_update_time": "",
        "status": "idle",
        "last_error": "",
        "download_progress": 0,
    }


def ensure_dirs() -> None:
    os.makedirs(OTA_DOWNLOAD_DIR, mode=0o700, exist_ok=True)


def load_state() -> Dict[str, Any]:
    ensure_dirs()
    if not os.path.isfile(OTA_STATE_FILE):
        state = default_state()
        save_state(state)
        return state
    try:
        with open(OTA_STATE_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        logger.error("Failed to read OTA state: %s", exc)
        return default_state()
    merged = default_state()
    merged.update(data)
    return merged


def save_state(state: Dict[str, Any]) -> None:
    ensure_dirs()
    tmp_path = OTA_STATE_FILE + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2, sort_keys=True)
            fh.write("\n")
        os.replace(tmp_path, OTA_STATE_FILE)
    except OSError as exc:
        logger.error("Failed to write OTA state: %s", exc)
        if os.path.isfile(tmp_path):
            os.remove(tmp_path)


def update_state(**fields) -> Dict[str, Any]:
    state = load_state()
    state.update(fields)
    save_state(state)
    return state


def set_status(status: str, error: str = "", **extra) -> Dict[str, Any]:
    if status not in STATUSES:
        raise ValueError(f"invalid OTA status: {status}")
    fields = {"status": status, "last_error": error}
    fields.update(extra)
    return update_state(**fields)


def mark_check_complete(available_version: str = "") -> Dict[str, Any]:
    return update_state(
        available_version=available_version,
        last_check_time=_utc_now(),
        status="idle",
        last_error="",
    )


def mark_pending_reboot(available_version: str) -> Dict[str, Any]:
    return update_state(
        available_version=available_version,
        last_check_time=_utc_now(),
        status="pending_reboot",
        last_error="",
        download_progress=100,
    )


def clear_pending_update() -> Dict[str, Any]:
    pending_file = os.path.join(OTA_DIR, "pending_version")
    if os.path.isfile(pending_file):
        try:
            os.remove(pending_file)
        except OSError as exc:
            logger.warning("Could not remove OTA pending version: %s", exc)

    for name in ("firmware.bin", "firmware.bin.part"):
        path = os.path.join(OTA_DOWNLOAD_DIR, name)
        if os.path.isfile(path):
            try:
                os.remove(path)
            except OSError as exc:
                logger.warning("Could not remove OTA download %s: %s", path, exc)

    return update_state(
        available_version="",
        status="idle",
        last_error="",
        download_progress=0,
    )


def mark_installed(version: str) -> Dict[str, Any]:
    return update_state(
        installed_version=version,
        available_version="",
        last_update_time=_utc_now(),
        status="success",
        last_error="",
        download_progress=0,
    )


def public_view(state: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    data = state or load_state()
    return {
        "installed_version": data.get("installed_version", Config.VERSION),
        "available_version": data.get("available_version", ""),
        "last_check_time": data.get("last_check_time", ""),
        "last_update_time": data.get("last_update_time", ""),
        "status": data.get("status", "idle"),
        "last_error": data.get("last_error", ""),
        "download_progress": data.get("download_progress", 0),
    }
