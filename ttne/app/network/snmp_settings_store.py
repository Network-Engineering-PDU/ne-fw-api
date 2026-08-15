"""Atomic persistence helpers for the SNMP API configuration."""

import json
import os
import threading
from typing import Tuple

from . import models


DEFAULT_CONFIG_FILE = "/home/root/.ne/snmp_config.json"
_lock = threading.Lock()


def save(path: str, basic: models.SnmpConfig,
         detailed: models.SnmpDetailedConfig) -> None:
    directory = os.path.dirname(path) or "."
    temporary = path + ".tmp"
    payload = {
        "settings": basic.dict(),
        "detailed_settings": detailed.dict(),
    }
    with _lock:
        os.makedirs(directory, exist_ok=True)
        try:
            with open(temporary, "w", encoding="utf-8") as config_file:
                json.dump(payload, config_file, sort_keys=True)
                config_file.write("\n")
                config_file.flush()
                os.fsync(config_file.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, path)
        except OSError:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise


def load(path: str, basic_default: models.SnmpConfig,
         detailed_default: models.SnmpDetailedConfig) -> Tuple[
             models.SnmpConfig, models.SnmpDetailedConfig
         ]:
    with _lock:
        try:
            with open(path, "r", encoding="utf-8") as config_file:
                payload = json.load(config_file)
            basic = models.SnmpConfig(**payload["settings"])
            detailed = models.SnmpDetailedConfig(
                **payload["detailed_settings"]
            )
            return basic, detailed
        except (FileNotFoundError, OSError, KeyError, TypeError, ValueError,
                json.JSONDecodeError):
            return basic_default, detailed_default


def preserve_v3_secrets(
        current: models.SnmpDetailedConfig,
        incoming: models.SnmpDetailedConfig) -> models.SnmpDetailedConfig:
    """Keep masked passwords when a client PUTs an unchanged V3 user."""
    old_v3 = current.snmp_v3
    new_v3 = incoming.snmp_v3
    if old_v3 is None or new_v3 is None or old_v3.usm_user != new_v3.usm_user:
        return incoming
    updates = {}
    if not new_v3.auth_pwd:
        updates["auth_pwd"] = old_v3.auth_pwd
    if not new_v3.privacy_pwd:
        updates["privacy_pwd"] = old_v3.privacy_pwd
    if not updates:
        return incoming
    return incoming.copy(update={"snmp_v3": new_v3.copy(update=updates)})
