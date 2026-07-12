import os
import re
import asyncio
import logging
import json

from ttne import utils
from ttne.network_config import NetworkConfig
from ttne.network_type import NetworkType
from . import models

logger = logging.getLogger(__name__)

SERVICES_FILE = "/home/root/.ne/services"
NETWORK_UI_CONFIG_FILE = "/home/root/.ne/network_ui_config.json"


def _load_network_ui_config():
    if not os.path.isfile(NETWORK_UI_CONFIG_FILE):
        return {}

    try:
        with open(NETWORK_UI_CONFIG_FILE, "r") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Can not read saved network UI config: %s", exc)
        return {}


def _save_network_ui_config(data):
    try:
        os.makedirs(os.path.dirname(NETWORK_UI_CONFIG_FILE), exist_ok=True)
        tmp_file = f"{NETWORK_UI_CONFIG_FILE}.tmp"
        with open(tmp_file, "w") as f:
            json.dump(data, f, indent=2, sort_keys=True)
            f.write("\n")
        os.replace(tmp_file, NETWORK_UI_CONFIG_FILE)
    except OSError as exc:
        logger.warning("Can not save network UI config: %s", exc)


def _forget_network_ui_config():
    try:
        os.remove(NETWORK_UI_CONFIG_FILE)
    except FileNotFoundError:
        pass
    except OSError as exc:
        logger.warning("Can not remove saved network UI config: %s", exc)


def _coalesce(*values):
    for value in values:
        if value is not None and value != "":
            return value
    return ""


def _saved_int(data, key, default):
    try:
        return int(data.get(key, default))
    except (TypeError, ValueError):
        return default

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
    ui_config = _load_network_ui_config()
    eth_iface = await nw_config._get_active_eth_if() or nw_config.eth_interface or "eth0"
    nw_config.eth_interface = eth_iface  # Store the detected interface

    nw_mode = _saved_int(ui_config, "nw_mode", nw_config.nw_mode)
    lan1_ip = _coalesce(ui_config.get("lan1_ip"), nw_config.lan1_ip, "192.168.1.100")
    lan2_ip = _coalesce(ui_config.get("lan2_ip"), nw_config.lan2_ip, "192.168.1.101")
    wifi_ip = _coalesce(ui_config.get("wifi_ip"), nw_config.wifi_ip)

    config_params = models.NetworkConfigParams(
        ip=_coalesce(ui_config.get("ip"), nw_config.ip),
        subnet_mask=_coalesce(ui_config.get("subnet_mask"), nw_config.mask),
        gateway_ip=_coalesce(ui_config.get("gateway_ip"), nw_config.gateway),
        dns=_coalesce(ui_config.get("dns"), f"{nw_config.dns1},{nw_config.dns2}"),
        ssid=_coalesce(ui_config.get("ssid"), nw_config.ssid),
        password="",
        eth_interface=_coalesce(ui_config.get("eth_interface"), nw_config.eth_interface)
    )
    network_config = models.MacNetworkConfig(
        type=_saved_int(ui_config, "type", nw_config.type),
        dhcp=ui_config.get(
            "dhcp",
            nw_config.type == NetworkType.ETH_DHCP or nw_config.type == NetworkType.WIFI_DHCP,
        ),
        params=config_params,
        ethernet_mac=await nw_config.get_mac(eth_iface),
        wifi_mac=await nw_config.get_mac("wlan0"),
        eth_interface=config_params.eth_interface,
        nw_mode=nw_mode,
        lan1_ip=lan1_ip,
        lan2_ip=lan2_ip,
        wifi_ip=wifi_ip,
    )
    logger.info(network_config)
    return network_config

async def set_network_config(config: models.BaseNetworkConfig):
    logger.info("Setting network configuration...")
    nw_config = NetworkConfig()
    nw_config.type = config.type
    nw_config.nw_mode = getattr(config, 'nw_mode', -1)
    nw_config.ssid = config.params.ssid or ""
    nw_config.psk = config.params.password or ""
    # Determine which ethernet interface to use. If the API explicitly provides
    # an `eth_interface` use that, otherwise try to auto-detect the active one.
    if getattr(config, 'eth_interface', None):
        nw_config.eth_interface = config.eth_interface
    else:
        detected = await nw_config._get_active_eth_if()
        nw_config.eth_interface = detected or "eth1"

    nw_config.lan1_ip = getattr(config, 'lan1_ip', None) or config.params.ip or "192.168.1.100"
    nw_config.lan2_ip = getattr(config, 'lan2_ip', None) or "192.168.1.101"
    nw_config.wifi_ip = getattr(config, 'wifi_ip', None) or ""

    _save_network_ui_config({
        "type": config.type,
        "dhcp": config.dhcp,
        "nw_mode": nw_config.nw_mode,
        "ip": config.params.ip or "",
        "subnet_mask": config.params.subnet_mask or "",
        "gateway_ip": config.params.gateway_ip or "",
        "dns": config.params.dns or "",
        "ssid": config.params.ssid or "",
        "eth_interface": nw_config.eth_interface or "",
        "lan1_ip": nw_config.lan1_ip,
        "lan2_ip": nw_config.lan2_ip,
        "wifi_ip": nw_config.wifi_ip,
    })

    if not config.dhcp:
        nw_config.ip = (
            nw_config.lan1_ip
            if nw_config.nw_mode == NetworkConfig.NW_DUAL_LAN
            else config.params.ip
        ) or nw_config.ip
        nw_config.mask = config.params.subnet_mask or nw_config.mask
        nw_config.gateway = config.params.gateway_ip or ""
        dnss = (config.params.dns or "").split(',')
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
    logger.info(f"Using ethernet interface: {nw_config.eth_interface}")

    await nw_config.save()

async def reset_network_config():
    logger.info("Resetting network configuration...")
    #TODO
    _forget_network_ui_config()
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
        await write_services(0, 0, 0)
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
