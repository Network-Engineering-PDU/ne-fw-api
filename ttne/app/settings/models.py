# pylint: disable=no-name-in-module
from typing import List, Optional

from pydantic import BaseModel, conint, validator
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


class PduInfoUpdate(BaseModel):
    rated_current: float


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
    installed_version: str = Config.VERSION
    available_version: str = ""
    last_check_time: str = ""
    last_update_time: str = ""
    ota_status: str = "idle"
    last_error: str = ""
    download_progress: int = 0
    check_interval_hours: int = 24
    ota_enabled: bool = True
    ota_provider: str = "github_repo"
    active_update_source: str = ""
    update_phase: str = "idle"
    update_busy: bool = False
    pending_source: str = ""


class UpdateSettings(BaseModel):
    auto_update: bool
    update_server: str
    check_interval_hours: int = 24
    ota_enabled: bool = True


class UpdateConfirm(BaseModel):
    confirm: bool


class BluetoothSettings(BaseModel):
    powered: Optional[bool] = None
    pairable: Optional[bool] = None
    discoverable: Optional[bool] = None


class BluetoothDevice(BaseModel):
    mac: str
    name: str = ""
    paired: bool = False
    trusted: bool = False
    connected: bool = False
    rssi: Optional[int] = None


class BluetoothStatus(BaseModel):
    controller_mac: str = ""
    name: str = ""
    powered: bool = False
    pairable: bool = False
    discoverable: bool = False
    discovering: bool = False
    pairing_request: bool = False
    pairing_mac: str = ""
    pairing_name: str = ""
    pairing_passkey: str = ""
    devices: List[BluetoothDevice] = []


class NtpSettings(BaseModel):
    enabled: bool = True
    time_offset: conint(ge=-12, le=12) = 0
    server: str = "0.openembedded.pool.ntp.org"

    @validator("server")
    def server_must_be_valid(cls, value):
        from ttne.ntp_config import validate_server
        return validate_server(value)


class NtpStatus(NtpSettings):
    running: bool = False
    synchronized: bool = False
