"""Touchscreen date and time settings: the time zone and clock format the
display shows, and setting the clock by hand while NTP is off.

The system clock stays in UTC (/etc/localtime is on the read-only image);
the display converts it with the time zone saved here. The board has no
backup battery for its clock: after a power loss the clock starts again
from the image's build date, so a clock before MIN_VALID_YEAR is reported
as not set.
"""

import json
import logging
import os
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from ttne import ntp_config, utils


logger = logging.getLogger(__name__)

DATETIME_SETTINGS_FILE = "/home/root/.ne/datetime_settings.json"
ZONEINFO_DIR = "/usr/share/zoneinfo"
ZONE_TABLE = ZONEINFO_DIR + "/zone1970.tab"
UTC_ZONE = "UTC"
HOUR_FORMATS = (12, 24)
DEFAULT_SETTINGS = {
    "timezone": UTC_ZONE,
    "hour_format": 24,
}
MIN_VALID_YEAR = 2024
# The display is 32-bit: its time_t ends in January 2038.
MAX_YEAR = 2037
LOCAL_TIME_FORMAT = "%Y-%m-%d %H:%M"

_timezones: Optional[List[str]] = None


def timezones() -> List[str]:
    """The canonical zones of the tz database (as the display lists them),
    and UTC."""
    global _timezones
    if _timezones is None:
        zones = {UTC_ZONE}
        try:
            with open(ZONE_TABLE, "r", encoding="utf-8") as table:
                for line in table:
                    fields = line.rstrip("\n").split("\t")
                    if not line.startswith("#") and len(fields) >= 3:
                        zones.add(fields[2])
        except OSError as exc:
            logger.warning("Can not read the time zone table: %s", exc)
        _timezones = sorted(zones)
    return _timezones


def validate_timezone(value: str) -> str:
    if value not in timezones() or not os.path.isfile(
            os.path.join(ZONEINFO_DIR, value)):
        raise ValueError("Unknown time zone")
    return value


def normalize_settings(settings: Dict[str, Any]) -> Dict[str, Any]:
    hour_format = settings.get("hour_format", DEFAULT_SETTINGS["hour_format"])
    if isinstance(hour_format, bool) or hour_format not in HOUR_FORMATS:
        raise ValueError("Hour format must be 12 or 24")
    return {
        "timezone": validate_timezone(
            settings.get("timezone", DEFAULT_SETTINGS["timezone"])),
        "hour_format": hour_format,
    }


def load_settings() -> Dict[str, Any]:
    try:
        with open(DATETIME_SETTINGS_FILE, "r", encoding="utf-8") as source:
            return normalize_settings(json.load(source))
    except FileNotFoundError:
        return dict(DEFAULT_SETTINGS)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        logger.warning("Invalid date and time settings; using defaults: %s",
                       exc)
        return dict(DEFAULT_SETTINGS)


def save_settings(settings: Dict[str, Any]) -> Dict[str, Any]:
    normalized = normalize_settings(settings)
    ntp_config._atomic_write(
        DATETIME_SETTINGS_FILE,
        json.dumps(normalized, indent=2, sort_keys=True) + "\n",
    )
    return normalized


def clock_is_set(now: Optional[float] = None) -> bool:
    now = time.time() if now is None else now
    return time.gmtime(now).tm_year >= MIN_VALID_YEAR


def parse_local_time(value: str) -> datetime:
    try:
        parsed = datetime.strptime(value, LOCAL_TIME_FORMAT)
    except (TypeError, ValueError):
        raise ValueError("Time must be YYYY-MM-DD HH:MM") from None
    if not MIN_VALID_YEAR <= parsed.year <= MAX_YEAR:
        raise ValueError(
            f"Year must be between {MIN_VALID_YEAR} and {MAX_YEAR}")
    return parsed


async def set_clock(local_time: str, timezone: str) -> bool:
    """Sets the system clock to local_time in timezone, and the hardware
    clock from it so the time survives a reboot (not a power loss)."""
    parsed = parse_local_time(local_time)
    validate_timezone(timezone)
    # GNU date reads the zone from the date string itself.
    value = f'TZ="{timezone}" {parsed.strftime(LOCAL_TIME_FORMAT)}'
    return_code, output = await utils.exec_command("date", "-s", value)
    if return_code != 0:
        logger.error("Could not set the clock: %s", output.strip())
        return False
    return_code, output = await utils.exec_command(
        "hwclock", "--systohc", "--utc")
    if return_code != 0:
        logger.warning("Could not set the hardware clock: %s", output.strip())
    return True


async def status() -> Dict[str, Any]:
    ntp = ntp_config.load_settings()
    ntp_status = await ntp_config.service_status()
    return {
        **load_settings(),
        "clock_set": clock_is_set(),
        "ntp_enabled": ntp["enabled"],
        "synchronized": ntp_status["synchronized"],
    }
