import os
import re
import asyncio
import logging
import json
import ipaddress

from ttne import utils
from ttne.network_config import NetworkConfig
from ttne.network_type import NetworkType
from . import models

logger = logging.getLogger(__name__)

SERVICES_FILE = "/home/root/.ne/services"
NETWORK_UI_CONFIG_FILE = "/home/root/.ne/network_ui_config.json"
NETWORK_APPLY_LOCK_FILE = "/tmp/ttne_network_apply.lock"
NETWORK_APPLY_MUTEX = asyncio.Lock()
DEFAULT_LAN1_IP = "192.168.1.100"
DEFAULT_LAN2_IP = "192.168.1.200"
DEFAULT_GATEWAY = "192.168.1.1"
LEGACY_DEFAULT_LAN2_IP = "192.168.1.101"


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


def _normalize_lan2_ip(value):
    if value == LEGACY_DEFAULT_LAN2_IP:
        return DEFAULT_LAN2_IP
    return value


def _saved_int(data, key, default):
    try:
        return int(data.get(key, default))
    except (TypeError, ValueError):
        return default


def _to_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _validate_ipv4(value, field, allow_empty=False):
    if value is None or value == "":
        if allow_empty:
            return
        raise ValueError(f"{field} is required")
    try:
        ipaddress.IPv4Address(value)
    except ipaddress.AddressValueError as exc:
        raise ValueError(f"{field} is not a valid IPv4 address") from exc


def validate_network_config(config: models.BaseNetworkConfig):
    ethernet_types = {NetworkType.ETH_DHCP, NetworkType.ETH_STATIC}
    wifi_types = {NetworkType.WIFI_DHCP, NetworkType.WIFI_STATIC}
    if config.type not in ethernet_types | wifi_types:
        raise ValueError("Invalid network type")

    valid_modes = {
        NetworkConfig.NW_SINGLE_LAN,
        NetworkConfig.NW_WIFI_ONLY,
        NetworkConfig.NW_DUAL_LAN,
        NetworkConfig.NW_LAN_WIFI,
        -1,
    }
    if config.nw_mode not in valid_modes:
        raise ValueError("Invalid network mode")
    if (
        config.nw_mode in (
            NetworkConfig.NW_SINGLE_LAN,
            NetworkConfig.NW_DUAL_LAN,
            NetworkConfig.NW_LAN_WIFI,
        )
        and config.type not in ethernet_types
    ):
        raise ValueError("Selected LAN mode requires an Ethernet network type")
    if (
        config.nw_mode == NetworkConfig.NW_WIFI_ONLY
        and config.type not in wifi_types
    ):
        raise ValueError("WiFi-only mode requires a WiFi network type")

    requested_iface = config.eth_interface or config.params.eth_interface
    if requested_iface and requested_iface not in NetworkType.get_available_eth_interfaces():
        raise ValueError("Invalid Ethernet interface")

    for value, field in (
        (config.params.ip, "IP address"),
        (config.params.gateway_ip, "Gateway"),
        (config.lan1_ip, "LAN1 IP address"),
        (config.lan1_gateway, "LAN1 gateway"),
        (config.lan2_ip, "LAN2 IP address"),
        (config.lan2_gateway, "LAN2 gateway"),
        (config.wifi_ip, "WiFi IP address"),
    ):
        _validate_ipv4(value, field, allow_empty=True)

    if config.params.subnet_mask:
        try:
            ipaddress.IPv4Network(
                f"0.0.0.0/{config.params.subnet_mask}",
                strict=False,
            )
        except (ipaddress.AddressValueError, ipaddress.NetmaskValueError) as exc:
            raise ValueError("Invalid subnet mask") from exc

    if config.params.dns:
        for dns in config.params.dns.split(","):
            _validate_ipv4(dns.strip(), "DNS server", allow_empty=True)

    if not config.dhcp:
        _validate_ipv4(config.params.ip, "IP address")
        if not config.params.subnet_mask:
            raise ValueError("Subnet mask is required")
        if config.nw_mode == NetworkConfig.NW_DUAL_LAN:
            for address, gateway, name in (
                (config.lan1_ip, config.lan1_gateway, "LAN1"),
                (config.lan2_ip, config.lan2_gateway, "LAN2"),
            ):
                _validate_ipv4(address, f"{name} IP address")
                _validate_ipv4(gateway, f"{name} gateway")
                network = ipaddress.IPv4Network(
                    f"{address}/{config.params.subnet_mask}", strict=False
                )
                if ipaddress.IPv4Address(gateway) not in network:
                    raise ValueError(
                        f"{name} gateway must be in the same subnet as {name}"
                    )

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
    detected_eth_iface = await nw_config._get_active_eth_if()
    eth_iface = _coalesce(
        ui_config.get("eth_interface"),
        nw_config.eth_interface,
        detected_eth_iface,
        "eth0",
    )
    nw_config.eth_interface = eth_iface  # Store the detected interface

    nw_mode = _saved_int(ui_config, "nw_mode", nw_config.nw_mode)
    lan1_ip = _coalesce(ui_config.get("lan1_ip"), nw_config.lan1_ip, DEFAULT_LAN1_IP)
    lan2_ip = _normalize_lan2_ip(
        _coalesce(ui_config.get("lan2_ip"), nw_config.lan2_ip, DEFAULT_LAN2_IP)
    )
    legacy_gateway = _coalesce(
        ui_config.get("gateway_ip"), nw_config.gateway, DEFAULT_GATEWAY
    )
    lan1_gateway = (
        ui_config.get("lan1_gateway")
        if "lan1_gateway" in ui_config
        else _coalesce(nw_config.lan1_gateway, legacy_gateway)
    )
    lan2_gateway = (
        ui_config.get("lan2_gateway")
        if "lan2_gateway" in ui_config
        else (nw_config.lan2_gateway or "")
    )
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
        lan1_gateway=lan1_gateway,
        lan2_ip=lan2_ip,
        lan2_gateway=lan2_gateway,
        wifi_ip=wifi_ip,
    )
    logger.info(network_config)
    return network_config


def save_network_ui_config(
    config: models.BaseNetworkConfig,
    eth_interface: str = None,
    lan1_ip: str = None,
    lan2_ip: str = None,
    wifi_ip: str = None,
):
    if eth_interface is None:
        eth_interface = (
            config.eth_interface or
            config.params.eth_interface or
            ""
        )

    lan1_ip = (
        lan1_ip or
        getattr(config, 'lan1_ip', None) or
        config.params.ip or
        DEFAULT_LAN1_IP
    )
    lan2_ip = (
        lan2_ip or
        getattr(config, 'lan2_ip', None) or
        DEFAULT_LAN2_IP
    )
    wifi_ip = wifi_ip or getattr(config, 'wifi_ip', None) or ""

    _save_network_ui_config({
        "type": config.type,
        "dhcp": config.dhcp,
        "nw_mode": getattr(config, 'nw_mode', -1),
        "ip": config.params.ip or "",
        "subnet_mask": config.params.subnet_mask or "",
        "gateway_ip": config.params.gateway_ip or "",
        "dns": config.params.dns or "",
        "ssid": config.params.ssid or "",
        "eth_interface": eth_interface,
        "lan1_ip": lan1_ip,
        "lan1_gateway": (
            getattr(config, "lan1_gateway", None)
            if getattr(config, "lan1_gateway", None) is not None
            else (config.params.gateway_ip or "")
        ),
        "lan2_ip": lan2_ip,
        "lan2_gateway": getattr(config, "lan2_gateway", None) or "",
        "wifi_ip": wifi_ip,
    })


async def set_network_config(config: models.BaseNetworkConfig):
    validate_network_config(config)
    async with NETWORK_APPLY_MUTEX:
        await _set_network_config_locked(config)


async def _set_network_config_locked(config: models.BaseNetworkConfig):
    logger.info("Setting network configuration...")
    try:
        with open(NETWORK_APPLY_LOCK_FILE, "w") as f:
            f.write(str(os.getpid()))

        nw_config = NetworkConfig()
        nw_config.type = config.type
        nw_config.nw_mode = _to_int(getattr(config, 'nw_mode', -1), -1)
        nw_config.ssid = config.params.ssid or ""
        nw_config.psk = config.params.password or ""
        linked_ifaces = await nw_config._get_linked_eth_interfaces()
        detected = await nw_config._get_active_eth_if()
        requested_iface = getattr(config, 'eth_interface', None)

        if nw_config.nw_mode in (NetworkConfig.NW_SINGLE_LAN, NetworkConfig.NW_LAN_WIFI):
            if requested_iface in linked_ifaces:
                nw_config.eth_interface = requested_iface
            elif linked_ifaces:
                nw_config.eth_interface = linked_ifaces[0]
            else:
                nw_config.eth_interface = detected or requested_iface or ""
        elif requested_iface:
            nw_config.eth_interface = requested_iface
        else:
            nw_config.eth_interface = detected or "eth1"

        nw_config.lan1_ip = getattr(config, 'lan1_ip', None) or config.params.ip or DEFAULT_LAN1_IP
        nw_config.lan1_gateway = (
            getattr(config, "lan1_gateway", None)
            if getattr(config, "lan1_gateway", None) is not None
            else (config.params.gateway_ip or "")
        )
        nw_config.lan2_ip = _normalize_lan2_ip(
            getattr(config, 'lan2_ip', None) or DEFAULT_LAN2_IP
        )
        nw_config.lan2_gateway = getattr(config, "lan2_gateway", None) or ""
        nw_config.wifi_ip = getattr(config, 'wifi_ip', None) or ""

        save_network_ui_config(
            config,
            eth_interface=nw_config.eth_interface or "",
            lan1_ip=nw_config.lan1_ip,
            lan2_ip=nw_config.lan2_ip,
            wifi_ip=nw_config.wifi_ip,
        )

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
        logger.info(nw_config.ip)
        logger.info(nw_config.mask)
        logger.info(nw_config.gateway)
        logger.info(nw_config.dns1)
        logger.info(nw_config.dns2)
        logger.info(f"Using ethernet interface: {nw_config.eth_interface}")

        await nw_config.save()
    finally:
        try:
            os.remove(NETWORK_APPLY_LOCK_FILE)
        except FileNotFoundError:
            pass

async def reset_network_config():
    logger.info("Resetting network configuration...")
    async with NETWORK_APPLY_MUTEX:
        try:
            with open(NETWORK_APPLY_LOCK_FILE, "w") as f:
                f.write(str(os.getpid()))
            _forget_network_ui_config()
            nw_config = NetworkConfig()
            await nw_config.reset_nw_config()
        finally:
            try:
                os.remove(NETWORK_APPLY_LOCK_FILE)
            except FileNotFoundError:
                pass

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
