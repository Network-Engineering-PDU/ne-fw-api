import asyncio
import logging
from datetime import datetime as dt
from typing import List, Union

from fastapi import APIRouter, Response, File, UploadFile

from ttne.server import PDU
from ttne.sn_pn_generator import *
from . import models, functions
from .. import gateway_helper

MODULE_NAME = "settings"

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/" + MODULE_NAME,
    tags=[MODULE_NAME],
    responses={404: {"description": "Not found", "module": MODULE_NAME}},
)

@router.get("/system-info")
async def get_system_info() -> models.SystemInfo:
    lan_mac = await functions.get_mac_address()
    iface_en = await functions.get_iface_en()
    ip = await functions.get_ip(iface_en)
    uptime = functions.uptime()
    sn, pn = read_snpn()
    return models.SystemInfo(product_pn=pn, product_sn=sn, lan_mac=lan_mac, ip=ip, uptime=uptime)

@router.get("/snmp-nms")
async def get_snmp_nms() -> models.SnmpNms:
    name, contact, location = await functions.read_snmp_nms()
    if name or contact or location:
        return models.SnmpNms(system_name=name, system_contact=contact, system_location=location)
    return models.SnmpNms()

@router.put("/snmp-nms")
async def put_snmp_nms(data: models.SnmpNms):
    await functions.write_snmp_nms(data.system_name, data.system_contact, data.system_location)

@router.post("/swupdate")
async def post_swupdate(data: models.SWUpdate):
    functions.update(data.filename)

@router.post("/system-reboot")
async def post_system_reboot():
    functions.reboot()

@router.post("/factory-reset")
async def post_factory_reset():
    functions.factory_reset()

pdu_profiles = [
    models.PduProfile(id=1, datetime=dt.now().strftime("%Y-%m-%d %H:%M:%S"))
]
profile_index = 1

@router.get("/pdu-profiles")
async def get_pdu_profiles() -> List[models.PduProfile]:
    return pdu_profiles

@router.get("/pdu-profiles/{profile_id}")
async def get_pdu_profiles_id(profile_id: int, response: Response) -> Union[models.PduProfile, None]:
    for profile in pdu_profiles:
        if profile.id == profile_id:
            return profile
    response.status_code = 404

@router.post("/pdu-profiles")
async def post_pdu_profile():
    global profile_index
    profile_index += 1
    pdu_profiles.append(models.PduProfile(id=profile_index, datetime=dt.now().strftime("%Y-%m-%d %H:%M:%S")))

@router.delete("/pdu-profiles/{profile_id}")
async def delete_pdu_profile_id(profile_id: int, response: Response):
    for profile in list(pdu_profiles):
        if profile.id == profile_id:
            pdu_profiles.remove(profile)
            return
    response.status_code = 404
    return

@router.post("/ca-cert")
async def post_ca_cert(file: bytes = File()):
    await functions.ca_cert(file)

@router.post("/ca-key")
async def post_ca_key(file: bytes = File()):
    await functions.ca_key(file)

@router.get("/pdu-info")
async def get_pdu_info() -> models.PduInfo:
    n_outlets = len(PDU.get_om())
    return models.PduInfo(outlet_count=n_outlets, rated_current=32.0,
            controller="VAR-SOM-MX7", type="SMART_PDU")

@router.post("/start-scan")
async def post_start_scan():
# async def post_start_scan() -> models.StartScanRsp:
    success = await functions.start_scan()
    return models.StartScanRsp(success=success)

@router.post("/stop-scan")
async def post_stop_scan() -> models.StopScanRsp:
    success = await gateway_helper.stop_scan()
    return models.StopScanRsp(success=success)

@router.put("/license")
async def put_license(data: models.License):
    await functions.write_license(data.type_id, data.expiration_date)

@router.get("/license")
async def get_license() -> models.License:
    type_id = await functions.read_license()
    return models.License(type_id=type_id)

@router.post("/start-ssh")
async def post_start_ssh():
    await functions.start_ssh()

@router.post("/stop-ssh")
async def post_stop_ssh():
    await functions.stop_ssh()

@router.post("/start-snmp")
async def post_start_snmp():
    await functions.start_snmp()

@router.post("/stop-snmp")
async def post_stop_snmp():
    await functions.stop_snmp()

@router.post("/start-modbus")
async def post_start_modbus():
    await functions.start_modbus()

@router.post("/stop-modbus")
async def post_stop_modbus():
    await functions.stop_modbus()

@router.put("/modbus")
async def put_modbus_addr(data: models.Modbus):
    await functions.write_modbus(data.addr)
    await asyncio.sleep(0.5)
    await functions.stop_modbus()
    await asyncio.sleep(0.5)
    await functions.start_modbus()

@router.get("/modbus")
async def get_modbus_addr() -> models.Modbus:
    addr = await functions.read_modbus()
    return models.Modbus(addr=addr)


# Auto-Update Endpoints

@router.get("/auto-update-config")
async def get_auto_update_config(enabled: int = 0) -> models.AutoUpdateConfig:
    """Enable or disable auto-update checking"""
    success = await functions.set_auto_update_config(bool(enabled))
    return models.AutoUpdateConfig(
        enabled=bool(enabled),
        message=f"Auto-update {'enabled' if enabled else 'disabled'}"
    )


@router.get("/auto-update-check")
async def auto_update_check() -> models.AutoUpdateCheck:
    """Check if new firmware version is available"""
    try:
        result = await functions.check_for_updates()
        return models.AutoUpdateCheck(
            version_available=result.get('version_available', False),
            current_version=result.get('current_version', 'unknown'),
            new_version=result.get('new_version'),
            changelog=result.get('changelog')
        )
    except Exception as e:
        logger.error(f"Error checking for updates: {e}")
        return models.AutoUpdateCheck(
            version_available=False,
            current_version="unknown",
            new_version=None,
            changelog=None
        )


@router.post("/auto-update-start")
async def auto_update_start() -> models.AutoUpdateStart:
    """Start the firmware auto-update process
    
    Shows "Updating..." on display, applies firmware, and reboots system
    """
    try:
        result = await functions.start_auto_update()
        return models.AutoUpdateStart(
            status=result.get('status', 'error'),
            message=result.get('message', 'Unknown error')
        )
    except Exception as e:
        logger.error(f"Error starting auto-update: {e}")
        return models.AutoUpdateStart(
            status="error",
            message=f"Failed to start update: {str(e)}"
        )
    return models.Modbus(addr=addr)