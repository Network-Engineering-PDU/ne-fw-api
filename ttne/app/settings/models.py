# pylint: disable=no-name-in-module
from pydantic import BaseModel
from ttne.config import Config
from ttne.version import OM_VERSION, PMB_VERSION

class SystemInfo(BaseModel):
    product_name: str = "NET-POWER"
    product_pn: str
    product_sn: str
    lan_mac: str
    ip: str
    sw_version: str = Config.VERSION
    om_version: str = OM_VERSION
    pmb_version: str = PMB_VERSION
    uptime: str


class SnmpNms(BaseModel):
    system_name: str = "NET-POWER"
    system_contact: str = ""
    system_location: str = ""


class PduProfile(BaseModel):
    id: int
    datetime: str


class PduInfo(BaseModel):
    outlet_count: int
    rated_current: float
    controller: str
    type: str


class StartScanRsp(BaseModel):
    success: bool


class StopScanRsp(BaseModel):
    success: bool


class License(BaseModel):
    type_id: str = "A1"


class Modbus(BaseModel):
    addr: int = 0

class SWUpdate(BaseModel):
    filename: str


class UpdateStatus(BaseModel):
    is_pending: bool = False
    auto_update: bool = False
    update_server: str = ""


class UpdateSettings(BaseModel):
    auto_update: bool
    update_server: str = ""


class UpdateConfirm(BaseModel):
    confirm: bool