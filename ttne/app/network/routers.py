import json
import os

from fastapi import APIRouter, HTTPException, Response

from ttne import utils
from ttne.network_config import NetworkConfig
from . import models, functions


MODULE_NAME = "network"
SNMP_CONFIG_FILE = "/home/root/.ne/snmp_config.json"

router = APIRouter(
    prefix="/" + MODULE_NAME,
    tags=[MODULE_NAME],
    responses={404: {"description": "Not found", "module": MODULE_NAME}},
)

@router.get("/info")
async def get_info(response: Response) -> models.NetworkInfo:
    info = await functions.get_network_info()
    if info is None:
        response.status_code = 404
        return
    return info

@router.get("/interfaces")
async def get_interfaces(response: Response) -> models.MacNetworkConfig:
    interfaces = await functions.get_network_config()
    if interfaces is None:
        response.status_code = 404
        return
    return interfaces

@router.put("/interfaces")
async def put_interfaces(data: models.BaseNetworkConfig, response: Response):
    if not data.dhcp and None in (data.params.ip, data.params.subnet_mask, data.params.gateway_ip, data.params.dns):
        response.status_code = 400
        return

    if data.type is None:
        response.status_code = 400
        return

    try:
        functions.validate_network_config(data)
    except ValueError:
        response.status_code = 400
        return

    if (
        data.nw_mode == NetworkConfig.NW_DUAL_LAN
        and data.lan1_ip
        and data.lan2_ip
        and data.lan1_ip == data.lan2_ip
    ):
        response.status_code = 400
        return

    # Persist the UI-visible selection before returning. Applying nmcli is
    # asynchronous because it can interrupt connectivity, but the screen may
    # refresh immediately after this response and must not see stale DHCP state.
    functions.save_network_ui_config(data)

    # Apply the network change asynchronously so the local display UI
    # is not blocked waiting for nmcli to finish reconfiguring the link.
    utils.schedule_in(0, functions.set_network_config(data))
    response.status_code = 202

@router.post("/reset")
async def put_reset():
    await functions.reset_network_config()

@router.get("/services")
async def get_services() -> models.Services:
    ssh, snmp, modbus = await functions.read_services()
    return models.Services(ssh=ssh, snmp=snmp, modbus=modbus)

@router.put("/services")
async def put_services(data: models.Services):
    await functions.write_services(data.ssh, data.snmp, data.modbus)

snmp_config = models.SnmpConfig(
    beep=True,
    relay=False,
    trap_alarm=True,
    email_alarm=True,
    refresh_period=60,
    life_time=240,
    datetime="2022-12-25 12:24:25",
    modbus_address=125
)

@router.get("/snmp/settings")
async def get_snmp_settings() -> models.SnmpConfig:
    return snmp_config

@router.put("/snmp/settings")
async def put_snmp_settings(data: models.SnmpConfig):
    global snmp_config
    snmp_config = data
    _save_snmp_settings()

snmp_detailed_settings = models.SnmpDetailedConfig(
    port=161,
    trap=models.SnmpTrapConfig(
        alarm=True,
        manager_1_name="Trap manager 1",
        manager_1_ip="192.168.0.11",
        manager_2_name="Trap manager 2",
        manager_2_ip="192.168.0.12"
    ),
    snmp_v1_v2c=models.SnmpV1Config(
        read_community="Public",
        write_community="Private"
    )
)


def _save_snmp_settings():
    os.makedirs(os.path.dirname(SNMP_CONFIG_FILE), exist_ok=True)
    temporary = SNMP_CONFIG_FILE + ".tmp"
    payload = {
        "settings": snmp_config.dict(),
        "detailed_settings": snmp_detailed_settings.dict(),
    }
    with open(temporary, "w", encoding="utf-8") as config_file:
        json.dump(payload, config_file, sort_keys=True)
        config_file.write("\n")
    os.chmod(temporary, 0o600)
    os.replace(temporary, SNMP_CONFIG_FILE)


def _load_snmp_settings():
    global snmp_config, snmp_detailed_settings
    try:
        with open(SNMP_CONFIG_FILE, "r", encoding="utf-8") as config_file:
            payload = json.load(config_file)
        snmp_config = models.SnmpConfig(**payload["settings"])
        snmp_detailed_settings = models.SnmpDetailedConfig(
            **payload["detailed_settings"]
        )
    except (FileNotFoundError, OSError, KeyError, TypeError, ValueError):
        return


_load_snmp_settings()

@router.get("/snmp/detailed-settings")
async def get_snmp_detailed_settings() -> models.SnmpDetailedConfig:
    detailed = snmp_detailed_settings.copy(deep=True)
    if detailed.snmp_v3:
        detailed.snmp_v3.auth_pwd = ""
        detailed.snmp_v3.privacy_pwd = ""
    return detailed

@router.put("/snmp/detailed-settings")
async def put_snmp_detailed_settings(data: models.SnmpDetailedConfig):
    global snmp_detailed_settings
    snmp_detailed_settings = data
    _save_snmp_settings()


def _manager_value(value):
    value = str(value or "").strip()
    return value or None


@router.get("/snmp/display-settings")
async def get_snmp_display_settings() -> models.SnmpDisplayConfig:
    _ssh, enabled, _modbus = await functions.read_services()
    version = snmp_detailed_settings.snmp_v1_v2c
    trap = snmp_detailed_settings.trap
    v3 = snmp_detailed_settings.snmp_v3
    return models.SnmpDisplayConfig(
        enabled=bool(enabled),
        version=snmp_detailed_settings.version,
        set_enabled=snmp_detailed_settings.set_enabled,
        community=(version.read_community if version else "public"),
        traps_enabled=bool(snmp_config.trap_alarm and trap.alarm),
        manager_1=trap.manager_1_ip,
        manager_2=trap.manager_2_ip,
        manager_3=trap.manager_3_ip,
        manager_4=trap.manager_4_ip,
        v3_user=(v3.usm_user if v3 else None),
        v3_security_level=(v3.security_level if v3 else "authPriv"),
        v3_auth_algorithm=(v3.auth_algorithm if v3 else "SHA"),
        v3_privacy_algorithm=(v3.privacy_algorithm if v3 else "AES"),
        v3_configured=bool(v3 and v3.usm_user),
    )


@router.put("/snmp/display-settings")
async def put_snmp_display_settings(
        data: models.SnmpDisplayConfig, response: Response
        ) -> models.SnmpDisplayConfig:
    global snmp_config, snmp_detailed_settings
    from ttne.app.settings import functions as settings_functions

    detailed = snmp_detailed_settings.dict()
    detailed["version"] = data.version
    detailed["set_enabled"] = data.set_enabled
    version = dict(detailed.get("snmp_v1_v2c") or {})
    version["read_community"] = data.community
    version.setdefault("write_community", "Private")
    detailed["snmp_v1_v2c"] = version
    trap = dict(detailed.get("trap") or {})
    trap["alarm"] = data.traps_enabled
    for index in range(1, 5):
        trap[f"manager_{index}_ip"] = _manager_value(
            getattr(data, f"manager_{index}")
        )
        trap.setdefault(f"manager_{index}_name", f"Trap manager {index}")
    detailed["trap"] = trap

    if data.version == "V3":
        if not data.v3_user:
            raise HTTPException(status_code=400, detail="V3 user is required")
        existing = snmp_detailed_settings.snmp_v3
        same_user = bool(existing and existing.usm_user == data.v3_user)
        auth_password = data.v3_auth_password or (
            existing.auth_pwd if same_user else ""
        )
        privacy_password = data.v3_privacy_password or (
            existing.privacy_pwd if same_user else ""
        )
        if (
            data.v3_security_level in ("authNoPriv", "authPriv")
            and len(auth_password) < 8
        ):
            raise HTTPException(
                status_code=400,
                detail="V3 authentication password must be at least 8 characters",
            )
        if (
            data.v3_security_level == "authPriv"
            and len(privacy_password) < 8
        ):
            raise HTTPException(
                status_code=400,
                detail="V3 privacy password must be at least 8 characters",
            )
        detailed["snmp_v3"] = models.Snmpv3Config(
            usm_user=data.v3_user,
            security_level=data.v3_security_level,
            access_right="readWrite" if data.set_enabled else "readOnly",
            auth_algorithm=data.v3_auth_algorithm,
            auth_pwd=auth_password,
            privacy_algorithm=data.v3_privacy_algorithm,
            privacy_pwd=privacy_password,
        ).dict()

    snmp_detailed_settings = models.SnmpDetailedConfig(**detailed)
    snmp_config = snmp_config.copy(update={
        "trap_alarm": data.traps_enabled,
    })
    _save_snmp_settings()
    if not await settings_functions.apply_snmp_configuration(data.enabled):
        response.status_code = 500
    return await get_snmp_display_settings()
