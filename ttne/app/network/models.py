# pylint: disable=no-name-in-module
from typing import Union, Optional

from pydantic import BaseModel


class NetworkInfo(BaseModel):
    connected: bool


class NetworkConfigParams(BaseModel):
    ip: Union[str, None] = None
    subnet_mask: Union[str, None] = None
    gateway_ip: Union[str, None] = None
    dns: Union[str, None] = None
    ssid: Union[str, None] = None
    password: Union[str, None] = None
    eth_interface: Optional[str] = None  # Ethernet port selection: eth0 (ETH-2) or eth1 (ETH-1)


class BaseNetworkConfig(BaseModel):
    type: int
    dhcp: bool
    params: NetworkConfigParams
    eth_interface: Optional[str] = None  # Ethernet port selection: eth0 (ETH-2) or eth1 (ETH-1)
    nw_mode: int = -1
    lan1_ip: Optional[str] = None
    lan2_ip: Optional[str] = None
    wifi_ip: Optional[str] = None


class MacNetworkConfig(BaseNetworkConfig):
    ethernet_mac: str
    wifi_mac: str


class Services(BaseModel):
    ssh: bool
    snmp: bool
    modbus: bool


class SnmpConfig(BaseModel):
    beep: bool
    relay: bool
    trap_alarm: bool
    email_alarm: bool
    refresh_period: int
    life_time: int
    datetime: str
    modbus_address: int


class SnmpTrapConfig(BaseModel):
    alarm: bool
    manager_1_name: Union[str, None] = None
    manager_1_ip: Union[str, None] = None
    manager_2_name: Union[str, None] = None
    manager_2_ip: Union[str, None] = None
    manager_3_name: Union[str, None] = None
    manager_3_ip: Union[str, None] = None
    manager_4_name: Union[str, None] = None
    manager_4_ip: Union[str, None] = None


class SnmpV1Config(BaseModel):
    read_community: str
    write_community: str


class Snmpv3Config(BaseModel):
    usm_user: str
    security_level: str
    access_right: str
    auth_algorithm: str
    auth_pwd: str
    privacy_algorithm: str
    privacy_pwd: str


class SnmpDetailedConfig(BaseModel):
    port: int
    trap: SnmpTrapConfig
    snmp_v1_v2c: Union[SnmpV1Config, None]
    snmp_v3: Union[Snmpv3Config, None]
