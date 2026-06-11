from fastapi import APIRouter, Response

from . import models, functions


MODULE_NAME = "network"

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

    # TODO: Return response and then connect
    await functions.set_network_config(data)

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

@router.get("/snmp/detailed-settings")
async def get_snmp_detailed_settings() -> models.SnmpDetailedConfig:
    return snmp_detailed_settings

@router.put("/snmp/detailed-settings")
async def put_snmp_detailed_settings(data: models.SnmpDetailedConfig):
    global snmp_detailed_settings
    snmp_detailed_settings = data
