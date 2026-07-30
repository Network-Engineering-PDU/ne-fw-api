"""Safe rendering of the runtime Net-SNMP configuration."""

import json
import logging
import os
import re


logger = logging.getLogger(__name__)

DEFAULT_SETTINGS_FILE = "/home/root/.ne/snmp_config.json"
DEFAULT_NMS_FILE = "/home/root/.ne/snmp_nms"


def _community(value, default):
    community = str(value or default)
    if community in ("Public", "Private"):
        community = community.lower()
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", community):
        logger.warning("Invalid SNMP community; using configured default")
        return default
    return community


def _config_string(value):
    text = (
        str(value or "")
        .replace("\r", " ")
        .replace("\n", " ")
        .replace("\0", "")
    )
    text = text.encode("utf-8")[:255].decode(
        "utf-8", errors="ignore"
    )
    return text.replace("\\", "\\\\").replace('"', '\\"')


def write_snmp_config(
        source="/usr/share/ttsnmp/ne_snmpd.conf",
        destination="/home/root/snmp/snmpd.conf",
        settings_file=DEFAULT_SETTINGS_FILE,
        nms_file=DEFAULT_NMS_FILE):
    with open(source, "r", encoding="utf-8") as config_file:
        lines = config_file.readlines()

    port = 161
    read_community = "public"
    write_community = "private"
    try:
        with open(settings_file, "r", encoding="utf-8") as config_file:
            detailed = json.load(config_file).get("detailed_settings", {})
        configured_port = detailed.get("port", port)
        if not isinstance(configured_port, bool):
            configured_port = int(configured_port)
            if 1 <= configured_port <= 65535:
                port = configured_port
        version = detailed.get("snmp_v1_v2c") or {}
        read_community = _community(
            version.get("read_community"), read_community
        )
        write_community = _community(
            version.get("write_community"), write_community
        )
    except (FileNotFoundError, OSError, TypeError, ValueError,
            json.JSONDecodeError):
        pass
    if read_community == write_community:
        logger.warning(
            "Read and write communities must differ; using a safe write "
            "community"
        )
        write_community = (
            "private" if read_community != "private" else "control"
        )

    name = "NET-POWER"
    contact = ""
    location = ""
    try:
        with open(nms_file, "r", encoding="utf-8") as nms_data_file:
            values = nms_data_file.read().split("\n", 2)
        values.extend([""] * (3 - len(values)))
        name, contact, location = values
    except OSError:
        pass

    replacements = {
        "agentAddress": f"agentAddress  udp:{port}\n",
        "override .1.3.6.1.2.1.1.4.0": (
            'override .1.3.6.1.2.1.1.4.0 octet_str '
            f'"{_config_string(contact)}"\n'
        ),
        "override .1.3.6.1.2.1.1.5.0": (
            'override .1.3.6.1.2.1.1.5.0 octet_str '
            f'"{_config_string(name)}"\n'
        ),
        "override .1.3.6.1.2.1.1.6.0": (
            'override .1.3.6.1.2.1.1.6.0 octet_str '
            f'"{_config_string(location)}"\n'
        ),
        "rocommunity": (
            f"rocommunity {read_community}\n"
        ),
        "rwcommunity": (
            f"rwcommunity {write_community} default "
            ".1.3.6.1.4.1.2000.1\n"
        ),
    }
    rendered = []
    for line in lines:
        replacement = next((
            value for prefix, value in replacements.items()
            if line.startswith(prefix)
        ), None)
        rendered.append(replacement if replacement is not None else line)

    temporary = destination + ".tmp"
    with open(temporary, "w", encoding="utf-8") as config_file:
        config_file.writelines(rendered)
        config_file.flush()
        os.fsync(config_file.fileno())
    os.chmod(temporary, 0o600)
    os.replace(temporary, destination)
