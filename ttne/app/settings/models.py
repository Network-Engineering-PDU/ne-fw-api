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
    wifi_licensed: bool = False
    outlet_switch_licensed: bool = False
    outlet_metering_licensed: bool = False


VALID_MODBUS_BAUD_RATES = (9600, 19200, 38400, 57600, 115200)
# Modbus RTU unit IDs: 0 is broadcast and 248-255 are reserved.
MODBUS_ADDR_MIN = 1
MODBUS_ADDR_MAX = 247
VALID_MODBUS_ROLES = ("slave", "master")
VALID_MODBUS_TIMEOUTS_MS = (100, 200, 500, 1000)
VALID_MODBUS_POLL_INTERVALS_S = (1, 2, 5, 10, 30)
VALID_MODBUS_OFFLINE_AFTER = (1, 2, 3, 5, 10)


def _one_of(name, value, valid):
    if value not in valid:
        raise ValueError(f"{name} must be one of {valid}")
    return value


def _modbus_id(name, value):
    if not MODBUS_ADDR_MIN <= value <= MODBUS_ADDR_MAX:
        raise ValueError(
            f"{name} must be between {MODBUS_ADDR_MIN} and {MODBUS_ADDR_MAX}")
    return value


class Modbus(BaseModel):
    addr: int = 1
    # RTU (RS-485, the "485" ports). Data bits are fixed at 8, same as the
    # hardware always ran before this was configurable.
    baud_rate: int = 115200
    parity: str = "N"  # N=none, E=even, O=odd
    stop_bits: int = 1
    # TCP (Modbus binds 0.0.0.0, so each NIC is gated independently here).
    tcp_eth1_enabled: bool = True
    tcp_eth2_enabled: bool = True
    # RTU: each 485 jack gated independently. Takes effect only on boards
    # where rtu_port_control is True.
    rtu_port1_enabled: bool = True
    rtu_port2_enabled: bool = True
    # Read-only: whether this board can switch each 485 jack on its own.
    # Always set by the API from the hardware; ignored when sent.
    rtu_port_control: bool = False
    # Daisy chain: a slave answers on the 485 bus at addr; a master polls
    # the other PDUs (IDs scan_first..scan_last) and addr is its own number.
    role: str = "slave"
    scan_first: int = 2
    scan_last: int = 16
    timeout_ms: int = 200
    poll_interval_s: int = 5
    offline_after: int = 3

    @validator("addr")
    def _valid_addr(cls, value):
        return _modbus_id("addr", value)

    @validator("baud_rate")
    def _valid_baud_rate(cls, value):
        return _one_of("baud_rate", value, VALID_MODBUS_BAUD_RATES)

    @validator("parity")
    def _valid_parity(cls, value):
        return _one_of("parity", value, ("N", "E", "O"))

    @validator("stop_bits")
    def _valid_stop_bits(cls, value):
        return _one_of("stop_bits", value, (1, 2))

    @validator("role")
    def _valid_role(cls, value):
        return _one_of("role", value, VALID_MODBUS_ROLES)

    @validator("scan_first", "scan_last")
    def _valid_scan_id(cls, value, field):
        return _modbus_id(field.name, value)

    @validator("timeout_ms")
    def _valid_timeout(cls, value):
        return _one_of("timeout_ms", value, VALID_MODBUS_TIMEOUTS_MS)

    @validator("poll_interval_s")
    def _valid_poll_interval(cls, value):
        return _one_of("poll_interval_s", value, VALID_MODBUS_POLL_INTERVALS_S)

    @validator("offline_after")
    def _valid_offline_after(cls, value):
        return _one_of("offline_after", value, VALID_MODBUS_OFFLINE_AFTER)


def modbus_settings_error(settings: dict) -> Optional[str]:
    """Checks that need several fields together, run on the complete
    settings (a PUT may send only some fields). Returns the problem as a
    sentence for the user, or None."""
    if settings["role"] != "master":
        return None
    if (settings["rtu_port_control"]
            and not settings["rtu_port1_enabled"]
            and not settings["rtu_port2_enabled"]):
        return "Tick at least one 485 port so the master can reach the chain"
    if settings["scan_first"] > settings["scan_last"]:
        return "The first scan ID must not be above the last scan ID"
    if settings["scan_first"] <= settings["addr"] <= settings["scan_last"]:
        return (f"Scan range includes this PDU's own number "
                f"({settings['addr']}). Change one of them.")
    return None


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


class DateTimeSettings(BaseModel):
    timezone: str = "UTC"
    hour_format: int = 24

    @validator("timezone")
    def timezone_must_be_known(cls, value):
        from ttne.datetime_config import validate_timezone
        return validate_timezone(value)

    @validator("hour_format")
    def hour_format_must_be_12_or_24(cls, value):
        if value not in (12, 24):
            raise ValueError("Hour format must be 12 or 24")
        return value


class DateTimeStatus(DateTimeSettings):
    clock_set: bool = False
    ntp_enabled: bool = True
    synchronized: bool = False


class ClockTime(BaseModel):
    local_time: str     # "YYYY-MM-DD HH:MM" in the saved time zone

    @validator("local_time")
    def local_time_must_be_valid(cls, value):
        from ttne.datetime_config import parse_local_time
        parse_local_time(value)
        return value
