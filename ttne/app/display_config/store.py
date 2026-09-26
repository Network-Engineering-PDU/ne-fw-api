"""Reads and writes the touchscreen's ``key=value`` config file.

The display (cmdisplay) owns this file. It re-reads it when it changes, so the
web UI can change display settings through this API.
"""
import os
import threading

from .models import DisplayConfig, TEXT_FIELDS

CONFIG_FILE = "/home/root/.cmdisplay.config"
_lock = threading.Lock()


def _parse(text: str) -> dict:
    values = {}
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            values[key.strip()] = value.strip()
    return values


def load_config(path=CONFIG_FILE) -> DisplayConfig:
    with _lock:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                raw = _parse(f.read())
        except OSError:
            raw = {}
    data = {}
    for key in ("rotation", "inactivity_time"):
        try:
            data[key] = int(raw[key])
        except (KeyError, ValueError):
            pass
    try:
        data["skip_login"] = int(raw["skip_login"]) != 0
    except (KeyError, ValueError):
        pass
    for key in TEXT_FIELDS:
        if key in raw:
            data[key] = raw[key][:255]
    try:
        return DisplayConfig(**data)
    except ValueError:
        # An out-of-range value in the file: fall back to defaults.
        return DisplayConfig()


def save_config(config: DisplayConfig, path=CONFIG_FILE) -> None:
    lines = [
        f"rotation={config.rotation}",
        f"inactivity_time={config.inactivity_time}",
        f"skip_login={1 if config.skip_login else 0}",
    ]
    lines += [f"{key}={getattr(config, key)}" for key in TEXT_FIELDS]
    directory = os.path.dirname(path)
    temporary = path + ".tmp"
    with _lock:
        os.makedirs(directory, exist_ok=True)
        try:
            with open(temporary, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(temporary, path)
        except OSError:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise
