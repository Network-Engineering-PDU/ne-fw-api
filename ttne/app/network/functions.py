import os
import re
import asyncio
import logging

from ttne import utils
from ttne.network_config import NetworkConfig
from ttne.network_type import NetworkType
from . import models

logger = logging.getLogger(__name__)

SERVICES_FILE = "/home/root/.ne/services"

async def get_iface_mac(iface: str) -> str:
    retval, output = await utils.shell(f"ip address show dev {iface}")
    if retval != 0 or output is None:
        return ""
    match = re.search(r"link/ether ([\d\w:]+)", output)
    if not match:
        return ""
    return match.group(1)


async def get_network_info() -> models.NetworkInfo:
    # TODO: ping
    network_info = models.NetworkInfo(connected=True)
    return network_info

async def get_network_config() -> models.MacNetworkConfig:
    logging.info("Getting network config...")
    nw_config = NetworkConfig()
    await nw_config.get_current_ip()
    await nw_config.get_wifi_ssid()
    await nw_config.get_static()
    eth_iface = await nw_config._get_active_eth_if() or "eth0"

    config_params = models.NetworkConfigParams(
        ip=nw_config.ip,
        subnet_mask=nw_config.mask,
        gateway_ip=nw_config.gateway,
        dns=f"{nw_config.dns1},{nw_config.dns2}",
        ssid=nw_config.ssid,
        password=""
    )
    network_config = models.MacNetworkConfig(
        type=nw_config.type,
        dhcp=(nw_config.type == NetworkType.ETH_DHCP or nw_config.type == NetworkType.WIFI_DHCP),
        params=config_params,
        ethernet_mac=await nw_config.get_mac(eth_iface),
        wifi_mac=await nw_config.get_mac("wlan0")
    )
    logger.info(network_config)
    return network_config

async def set_network_config(config: models.BaseNetworkConfig):
    logger.info("Setting network configuration...")
    nw_config = NetworkConfig()
    nw_config.type = config.type
    nw_config.ssid = config.params.ssid
    nw_config.psk = config.params.password

    if not config.dhcp:
        nw_config.ip = config.params.ip
        nw_config.mask = config.params.subnet_mask
        nw_config.gateway = config.params.gateway_ip
        dnss = config.params.dns.split(',')
        if len(dnss) > 0:
            nw_config.dns1 = dnss[0]
        if len(dnss) > 1:
            nw_config.dns2 = dnss[1]

    logger.info(nw_config.type)
    logger.info(nw_config.ssid)
    logger.info(nw_config.psk)
    logger.info(nw_config.ip)
    logger.info(nw_config.mask)
    logger.info(nw_config.gateway)
    logger.info(nw_config.dns1)
    logger.info(nw_config.dns2)

    await nw_config.save()

async def reset_network_config():
    logger.info("Resetting network configuration...")
    #TODO
    nw_config = NetworkConfig()
    await nw_config.reset_nw_config()

async def write_services(ssh, snmp, modbus):
    logger.info("Writing services")
    with open(SERVICES_FILE, 'w+') as f:
        f.write(f"{1 if ssh else 0},{1 if snmp else 0},{1 if modbus else 0}")

async def read_services():
    logger.info("Reading services")
    if not os.path.isfile(SERVICES_FILE):
        logger.warning("NO SERVICES FILE, CREATING A DEFAULT ONE")
        await write_services(1, 0, 0)
    with open(SERVICES_FILE, 'r+') as f:
        line = f.readline()
        if line[-1] == "\n":
            line = line[:-1]
        line_split = line.split(',', 3)
        ssh = int(line_split[0])
        snmp = int(line_split[1])
        modbus = int(line_split[2])
        logger.info(f"Services readed. SSH: {ssh}, SNMP: {snmp}, Modbus: {modbus}")
        return ssh, snmp, modbus
    return None, None, None
