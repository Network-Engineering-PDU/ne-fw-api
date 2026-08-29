# pylint: disable=no-name-in-module
import ipaddress
import re
from typing import Literal, Union, Optional

from pydantic import BaseModel, conint, constr, validator


SnmpCommunity = constr(regex=r"^[A-Za-z0-9_.-]{1,64}$")
SnmpV3User = constr(regex=r"^[A-Za-z0-9_.-]{1,32}$")
SnmpV3Password = constr(
    min_length=8,
    max_length=64,
    regex=r"^[A-Za-z0-9_.@#%+=:-]+$",
)
SnmpTrapTarget = constr(
    strip_whitespace=True,
    max_length=253,
    regex=r"^[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?$",
)


def _validated_trap_target(value):
    if value in (None, ""):
        return None
    value = str(value).strip()
    try:
        if ipaddress.ip_address(value).version != 4:
            raise ValueError("IPv6 trap targets are not supported")
        return value
    except ValueError as address_error:
        labels = value.rstrip(".").split(".")
        valid_dns = (
            not all(label.isdigit() for label in labels)
            and all(
                re.fullmatch(
                    r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?",
                    label,
                )
                for label in labels
            )
        )
        if not valid_dns:
            raise ValueError(
                "trap target must be an IPv4 address or DNS name"
            ) from address_error
        return value.rstrip(".").lower()


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
    lan1_gateway: Optional[str] = None
    lan2_ip: Optional[str] = None
    lan2_gateway: Optional[str] = None
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
    manager_1_ip: Optional[SnmpTrapTarget] = None
    manager_2_name: Union[str, None] = None
    manager_2_ip: Optional[SnmpTrapTarget] = None
    manager_3_name: Union[str, None] = None
    manager_3_ip: Optional[SnmpTrapTarget] = None
    manager_4_name: Union[str, None] = None
    manager_4_ip: Optional[SnmpTrapTarget] = None

    @validator(
        "manager_1_ip", "manager_2_ip", "manager_3_ip", "manager_4_ip",
        pre=True,
    )
    def validate_manager(cls, value):
        return _validated_trap_target(value)


class SnmpV1Config(BaseModel):
    read_community: SnmpCommunity
    write_community: SnmpCommunity


class Snmpv3Config(BaseModel):
    usm_user: str
    security_level: str
    access_right: str
    auth_algorithm: str
    auth_pwd: str
    privacy_algorithm: str
    privacy_pwd: str


class SnmpDetailedConfig(BaseModel):
    port: conint(ge=1, le=65535)
    trap: SnmpTrapConfig
    snmp_v1_v2c: Union[SnmpV1Config, None]
    snmp_v3: Union[Snmpv3Config, None]
    set_enabled: bool = True
    version: Literal["V1", "V2c", "V3"] = "V2c"

    @validator("version", pre=True)
    def migrate_combined_version(cls, value):
        return "V2c" if value == "V1/V2c" else value


class SnmpDisplayConfig(BaseModel):
    enabled: bool
    version: Literal["V1", "V2c", "V3"] = "V2c"
    set_enabled: bool
    community: SnmpCommunity
    traps_enabled: bool
    manager_1: Optional[SnmpTrapTarget] = None
    manager_2: Optional[SnmpTrapTarget] = None
    manager_3: Optional[SnmpTrapTarget] = None
    manager_4: Optional[SnmpTrapTarget] = None
    v3_user: Optional[SnmpV3User] = None
    v3_security_level: Literal[
        "noAuthNoPriv", "authNoPriv", "authPriv"
    ] = "authPriv"
    v3_auth_algorithm: Literal["MD5", "SHA"] = "SHA"
    v3_auth_password: Optional[SnmpV3Password] = None
    v3_privacy_algorithm: Literal["DES", "AES"] = "AES"
    v3_privacy_password: Optional[SnmpV3Password] = None
    v3_configured: bool = False

    @validator("version", pre=True)
    def migrate_combined_version(cls, value):
        return "V2c" if value == "V1/V2c" else value

    @validator(
        "manager_1", "manager_2", "manager_3", "manager_4", pre=True
    )
    def validate_trap_target(cls, value):
        return _validated_trap_target(value)

    @validator("v3_user", pre=True)
    def normalize_optional_v3_user(cls, value):
        return None if value in (None, "") else value
