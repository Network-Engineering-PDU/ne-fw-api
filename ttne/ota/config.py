"""OTA daemon configuration."""

import json
import logging
import os
from typing import Any, Dict

from ttne.config import Config

logger = logging.getLogger(__name__)

OTA_CONFIG_FILE = os.path.join(Config.TTNE_DIR, "ota_config.json")

DEFAULTS = {
    "enabled": True,
    "provider": "github_repo",
    "check_interval_hours": 24,
    "metadata_filename": "metadata.json",
    "staging_firmware": os.path.join(Config.TTNE_DIR, "ota", "downloads", "firmware.bin"),
    "github_owner": "Network-Engineering-PDU",
    "github_repo": "firmware-update",
    "github_ref": "main",
    "github_path": "",
    "github_token_path": "",
}


def load_config() -> Dict[str, Any]:
    cfg = dict(DEFAULTS)
    if not os.path.isfile(OTA_CONFIG_FILE):
        return cfg
    try:
        with open(OTA_CONFIG_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        cfg.update(data)
    except (OSError, json.JSONDecodeError) as exc:
        logger.error("Failed to read OTA config: %s", exc)
    return cfg


def save_config(cfg: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(OTA_CONFIG_FILE), exist_ok=True)
    tmp_path = OTA_CONFIG_FILE + ".tmp"
    merged = dict(DEFAULTS)
    merged.update(cfg)
    with open(tmp_path, "w", encoding="utf-8") as fh:
        json.dump(merged, fh, indent=2, sort_keys=True)
        fh.write("\n")
    os.replace(tmp_path, OTA_CONFIG_FILE)


def check_interval_seconds(cfg: Dict[str, Any]) -> int:
    hours = int(cfg.get("check_interval_hours", 24))
    if hours not in (1, 24):
        hours = 24
    return hours * 3600
