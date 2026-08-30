"""Safe rendering of the runtime Net-SNMP configuration."""

import json
import logging
import os
import re


logger = logging.getLogger(__name__)

DEFAULT_SETTINGS_FILE = "/home/root/.ne/snmp_config.json"
DEFAULT_NMS_FILE = "/home/root/.ne/snmp_nms"
DEFAULT_PERSISTENT_FILE = "/var/lib/net-snmp/snmpd.conf"
LOCAL_WARMUP_COMMUNITY = "_nee_internal_warmup_"


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


def _validated_v3(selected_version, v3):
    if selected_version != "V3" or not v3.get("usm_user"):
        return None
    user = str(v3.get("usm_user"))
    security = {
        "noAuthNoPriv": "noauth",
        "authNoPriv": "auth",
        "authPriv": "priv",
    }.get(v3.get("security_level"), "priv")
    auth_algorithm = v3.get("auth_algorithm", "SHA")
    privacy_algorithm = v3.get("privacy_algorithm", "AES")
    auth_password = str(v3.get("auth_pwd", ""))
    privacy_password = str(v3.get("privacy_pwd", ""))
    safe_user = re.fullmatch(r"[A-Za-z0-9_.-]{1,32}", user)
    safe_auth = re.fullmatch(
        r"[A-Za-z0-9_.@#%+=:-]{8,64}", auth_password
    )
    safe_privacy = re.fullmatch(
        r"[A-Za-z0-9_.@#%+=:-]{8,64}", privacy_password
    )
    if not (
        safe_user
        and auth_algorithm in ("MD5", "SHA")
        and privacy_algorithm in ("DES", "AES")
        and (security == "noauth" or safe_auth)
        and (security != "priv" or safe_privacy)
    ):
        logger.warning("Invalid SNMPv3 credentials; V3 access disabled")
        return None
    return {
        "user": user,
        "security": security,
        "auth_algorithm": auth_algorithm,
        "auth_password": auth_password,
        "privacy_algorithm": privacy_algorithm,
        "privacy_password": privacy_password,
        "read_write": bool(
            v3.get("access_right") == "readWrite"
        ),
    }


def _atomic_lines(path, lines):
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    temporary = path + ".tmp"
    try:
        with open(temporary, "w", encoding="utf-8") as config_file:
            config_file.writelines(lines)
            config_file.flush()
            os.fsync(config_file.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def write_snmp_v3_user(
        settings_file=DEFAULT_SETTINGS_FILE,
        persistent_file=DEFAULT_PERSISTENT_FILE):
    """Replace the application-managed USM user while snmpd is stopped."""
    detailed = {}
    try:
        with open(settings_file, "r", encoding="utf-8") as config_file:
            detailed = json.load(config_file).get("detailed_settings", {})
    except (FileNotFoundError, OSError, TypeError, ValueError,
            json.JSONDecodeError):
        pass
    selected_version = detailed.get("version", "V2c")
    if selected_version == "V1/V2c":
        selected_version = "V2c"
    credentials = _validated_v3(
        selected_version, detailed.get("snmp_v3") or {}
    )
    try:
        with open(persistent_file, "r", encoding="utf-8") as config_file:
            lines = config_file.readlines()
    except FileNotFoundError:
        lines = []
    lines = [
        line for line in lines
        if not line.lstrip().startswith(("createUser ", "usmUser "))
    ]
    if credentials:
        create_user = f"createUser {credentials['user']}"
        if credentials["security"] in ("auth", "priv"):
            create_user += (
                f" {credentials['auth_algorithm']} "
                f'"{credentials["auth_password"]}"'
            )
        if credentials["security"] == "priv":
            create_user += (
                f" {credentials['privacy_algorithm']} "
                f'"{credentials["privacy_password"]}"'
            )
        lines.append(create_user + "\n")
    _atomic_lines(persistent_file, lines)


def write_snmp_config(
        source="/usr/share/ttsnmp/ne_snmpd.conf",
        destination="/home/root/snmp/snmpd.conf",
        settings_file=DEFAULT_SETTINGS_FILE,
        nms_file=DEFAULT_NMS_FILE,
        persistent_file=DEFAULT_PERSISTENT_FILE):
    with open(source, "r", encoding="utf-8") as config_file:
        lines = config_file.readlines()

    port = 161
    read_community = "public"
    write_community = "private"
    set_enabled = True
    selected_version = "V2c"
    v3 = {}
    try:
        with open(settings_file, "r", encoding="utf-8") as config_file:
            detailed = json.load(config_file).get("detailed_settings", {})
        configured_port = detailed.get("port", port)
        if not isinstance(configured_port, bool):
            configured_port = int(configured_port)
            if 1 <= configured_port <= 65535:
                port = configured_port
        version = detailed.get("snmp_v1_v2c") or {}
        selected_version = detailed.get("version", selected_version)
        if selected_version == "V1/V2c":
            selected_version = "V2c"
        v3 = detailed.get("snmp_v3") or {}
        set_enabled = bool(detailed.get("set_enabled", True))
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

    v3_access = []
    credentials = _validated_v3(selected_version, v3)
    if credentials:
        directive = "rwuser" if (
            set_enabled and credentials["read_write"]
        ) else "rouser"
        v3_access.append(
            f"{directive} {credentials['user']} "
            f"{credentials['security']}\n"
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

    community_access = (
        "view neSnmpPdu included .1.3.6.1.4.1.2000.1\n"
        f"com2sec neSnmpWarm 127.0.0.1 {LOCAL_WARMUP_COMMUNITY}\n"
        "group neSnmpWarmGroup v2c neSnmpWarm\n"
        "access neSnmpWarmGroup \"\" v2c noauth exact "
        "neSnmpPdu none none\n"
    )
    if selected_version in ("V1", "V2c"):
        security_model = "v1" if selected_version == "V1" else "v2c"
        community_access += (
            "view neSnmpAll included .1\n"
            f"com2sec neSnmpRead default {read_community}\n"
            f"group neSnmpReadGroup {security_model} neSnmpRead\n"
            f'access neSnmpReadGroup "" {security_model} noauth exact '
            "neSnmpAll none none\n"
        )
        if set_enabled:
            community_access += (
                f"com2sec neSnmpWrite default {write_community}\n"
                f"group neSnmpWriteGroup {security_model} neSnmpWrite\n"
                f'access neSnmpWriteGroup "" {security_model} noauth exact '
                "neSnmpAll neSnmpPdu none\n"
            )

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
        "rocommunity": community_access,
        "rwcommunity": "",
    }
    rendered = []
    for line in lines:
        replacement = next((
            value for prefix, value in replacements.items()
            if line.startswith(prefix)
        ), None)
        rendered.append(replacement if replacement is not None else line)
    rendered.extend(v3_access)
    # snmpd is started with -C, so it does not load the standard persistent
    # configuration automatically.  Explicitly include it so a createUser
    # token written while the daemon is stopped is consumed and subsequently
    # persisted as a localized usmUser record.
    rendered.append(f"includeFile {persistent_file}\n")

    _atomic_lines(destination, rendered)
