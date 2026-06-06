import os
import re
import time
import shutil
import asyncio
import logging
import fnmatch
import pickle
import base64
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding

from ttne import utils
from ttne.app.network import functions as nw_functions
from ttne.sn_pn_generator import *
from .. import gateway_helper


logger = logging.getLogger(__name__)


SNMP_NMS_FILE = "/tmp/ne_fw_api_snmp_nms"
SWUPDATE_FILE = "/home/root/ttfile.bin"
CA_CERT_FILE = "/home/root/certs/cm.crt"
CA_KEY_FILE = "/home/root/certs/cm.key"
LICENSE_FILE = "/home/root/.ne/license"
MODBUS_FILE = "/home/root/.ne/modbus_addr"
COPY_FILE_BUFFER = 1024*1024

START_TIME = time.time()
BT_AGENT_PROCESS = None
BT_AGENT_PENDING = None
BT_AGENT_LAST_DEVICE = {"mac": "", "name": ""}


async def get_mac_address() -> str:
    lan_mac = "00:00:00:00:00:00"
    ret, output = await utils.shell("ip address")
    if ret == 0:
        match = re.search("link/ether ([a-z0-9:]+)", output)
        if match:
            lan_mac = match.groups()[0]
    return lan_mac


async def get_iface_en():
    iface_en = None
    retval, output = await utils.shell("nmcli -t d")
    ex_ifaces = ("lo", "p2p-dev-*", "sit*")
    if retval == 0 and output is not None:
        for line in output.splitlines():
            device = line.split(":", 4)[0].strip()
            match = [fnmatch.fnmatch(device, ex_if) for ex_if in ex_ifaces]
            if any(match):
                continue
            status = line.split(":", 4)[2].strip()
            if status == "connected":
                iface_en = line.split(":", 4)[0].strip()
    return iface_en


# TODO: iface?
async def get_ip(iface) -> str:
    ip = ""
    retval, output = await utils.shell(f"nmcli -t d show {iface}")
    if retval == 0 and output is not None:
        for line in output.splitlines():
            param = line.split(":", 1)
            if param[0] == "IP4.ADDRESS[1]":
                ip = param[1].split("/")[0]
    return ip


def uptime() -> str:
    elapsed_time = time.time() - START_TIME
    # TODO: what if hours > 99? should be: 1284:29; test with start_time -= years=10?
    return time.strftime("%H:%M", time.gmtime(elapsed_time))


async def read_snmp_nms() -> ["str", "str", "str"]:
    name = ""
    contact = ""
    location = ""
    data = await utils.read_file(SNMP_NMS_FILE)
    if data:
        name, contact, location = data.split("\n")
    return name, contact, location


async def write_snmp_nms(name, contact, location):
    data = "\n".join((name, contact, location))
    await utils.write_file(SNMP_NMS_FILE, data)


def update(update_file):
    logger.info("Saving update...")
    os.rename(update_file, SWUPDATE_FILE)
    logger.info("Update saved")
    
    # Check if auto-update is enabled
    auto_update, _ = _read_update_config()
    
    if auto_update:
        # Mark update as pending and wait for confirmation from PDU display
        _set_update_pending(True)
        logger.info("Update marked as pending, waiting for user confirmation from PDU")
    else:
        # Auto-update disabled, execute immediately
        logger.info("Auto-update disabled, executing update immediately")
        utils.schedule_in(5, utils.shell("usb_autorun.sh run " + SWUPDATE_FILE))
    
    # Clean up upload directory
    try:
        shutil.rmtree("/home/root/.ne/uploads")
        logger.info("Upload directory removed")
    except Exception as e:
        logger.warning(f"Could not remove upload directory: {e}")

    return {"is_pending": auto_update}

async def ca_cert(ca_cert_file):
    logger.info("Saving CA cert...")
    copy_fd = await asyncio.to_thread(open, CA_CERT_FILE, "wb")
    await asyncio.to_thread(copy_fd.write, ca_cert_file)
    await asyncio.to_thread(copy_fd.close)
    logger.info("CA cert saved")

async def ca_key(ca_key_file):
    logger.info("Saving CA key...")
    copy_fd = await asyncio.to_thread(open, CA_KEY_FILE, "wb")
    await asyncio.to_thread(copy_fd.write, ca_key_file)
    await asyncio.to_thread(copy_fd.close)
    logger.info("CA key saved")

def reboot():
    logger.info("Rebooting...")
    utils.schedule_in(5, utils.shell("reboot"))

def factory_reset():
    logger.info("Factory reset")
    logger.info("Resetting network settings and restoring system defaults before reboot...")

    try:
        asyncio.create_task(nw_functions.reset_network_config())
    except Exception as e:
        logger.warning(f"Network reset task failed: {e}")

    home_dir = os.path.expanduser("~/")
    cleanup_cmd = (
        f"rm -rf {home_dir}/* {home_dir}/.[!.]* {home_dir}/..?*; "
        f"mkdir -p {os.path.dirname(UPDATE_CONFIG_FILE)}; "
        f"printf 'true\\n\\n' > {UPDATE_CONFIG_FILE}; "
        f"mkdir -p {os.path.dirname(BLUETOOTH_CONFIG_FILE)}; "
        f"printf 'true\\n' > {BLUETOOTH_CONFIG_FILE}; "
        "reboot"
    )
    utils.schedule_in(5, utils.shell(cleanup_cmd))

async def start_scan():
    logger.info("Start scan")
    return await gateway_helper.start_scan()


def _parse_bt_bool(value: str) -> bool:
    return value.strip().lower() == "yes"


async def _bluetoothctl(*commands):
    cmd = " && ".join([f"echo '{command}'" for command in commands])
    return await utils.shell(f"({cmd}) | bluetoothctl")


async def _bt_agent_write(command):
    global BT_AGENT_PROCESS
    if BT_AGENT_PROCESS is None or BT_AGENT_PROCESS.returncode is not None:
        return False
    BT_AGENT_PROCESS.stdin.write((command + "\n").encode())
    await BT_AGENT_PROCESS.stdin.drain()
    return True


async def _bt_agent_reader(process):
    global BT_AGENT_PENDING, BT_AGENT_LAST_DEVICE
    while True:
        line = await process.stdout.readline()
        if not line:
            return
        text = line.decode(errors="replace").strip()
        logger.debug(f"bluetoothctl agent: {text}")

        device_match = re.search(r"Device ([0-9A-Fa-f:]{17})(?: (.*))?", text)
        if device_match:
            BT_AGENT_LAST_DEVICE = {
                "mac": device_match.group(1),
                "name": (device_match.group(2) or "").strip(),
            }

        request = any(phrase in text for phrase in (
            "Confirm passkey",
            "Authorize service",
            "Accept pairing",
            "Request confirmation",
            "Request authorization",
        ))
        if request:
            passkey_match = re.search(r"passkey\s+([0-9]+)", text, re.IGNORECASE)
            BT_AGENT_PENDING = {
                "mac": BT_AGENT_LAST_DEVICE["mac"],
                "name": BT_AGENT_LAST_DEVICE["name"] or "Bluetooth device",
                "passkey": passkey_match.group(1) if passkey_match else "",
            }


async def ensure_bluetooth_agent():
    global BT_AGENT_PROCESS
    if BT_AGENT_PROCESS is not None and BT_AGENT_PROCESS.returncode is None:
        return

    BT_AGENT_PROCESS = await asyncio.create_subprocess_exec(
        "bluetoothctl",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    asyncio.create_task(_bt_agent_reader(BT_AGENT_PROCESS))
    await asyncio.sleep(0.2)
    await _bt_agent_write("agent KeyboardDisplay")
    await _bt_agent_write("default-agent")


async def get_bluetooth_status():
    logger.info("Reading Bluetooth status")
    await ensure_bluetooth_agent()
    status = {
        "controller_mac": "",
        "name": "",
        "powered": False,
        "pairable": False,
        "discoverable": False,
        "discovering": False,
        "pairing_request": BT_AGENT_PENDING is not None,
        "pairing_mac": BT_AGENT_PENDING["mac"] if BT_AGENT_PENDING else "",
        "pairing_name": BT_AGENT_PENDING["name"] if BT_AGENT_PENDING else "",
        "pairing_passkey": BT_AGENT_PENDING["passkey"] if BT_AGENT_PENDING else "",
        "devices": [],
    }

    retval, output = await _bluetoothctl("show")
    if retval == 0 and output:
        for line in output.splitlines():
            line = line.strip()
            if line.startswith("Controller "):
                parts = line.split()
                if len(parts) > 1:
                    status["controller_mac"] = parts[1]
            elif line.startswith("Name:"):
                status["name"] = line.split(":", 1)[1].strip()
            elif line.startswith("Powered:"):
                status["powered"] = _parse_bt_bool(line.split(":", 1)[1])
            elif line.startswith("Pairable:"):
                status["pairable"] = _parse_bt_bool(line.split(":", 1)[1])
            elif line.startswith("Discoverable:"):
                status["discoverable"] = _parse_bt_bool(line.split(":", 1)[1])
            elif line.startswith("Discovering:"):
                status["discovering"] = _parse_bt_bool(line.split(":", 1)[1])

    retval, output = await _bluetoothctl("devices")
    if retval != 0 or not output:
        return status

    seen = set()
    for line in output.splitlines():
        line = line.strip()
        if not line.startswith("Device "):
            continue
        parts = line.split(" ", 2)
        if len(parts) < 2 or parts[1] in seen:
            continue
        mac = parts[1]
        seen.add(mac)
        fallback_name = parts[2] if len(parts) > 2 else mac
        device = {
            "mac": mac,
            "name": fallback_name,
            "paired": False,
            "trusted": False,
            "connected": False,
            "rssi": None,
        }

        info_retval, info_output = await _bluetoothctl(f"info {mac}")
        if info_retval == 0 and info_output:
            for info_line in info_output.splitlines():
                info_line = info_line.strip()
                if info_line.startswith("Name:"):
                    device["name"] = info_line.split(":", 1)[1].strip()
                elif info_line.startswith("Alias:") and not device["name"]:
                    device["name"] = info_line.split(":", 1)[1].strip()
                elif info_line.startswith("Paired:"):
                    device["paired"] = _parse_bt_bool(info_line.split(":", 1)[1])
                elif info_line.startswith("Trusted:"):
                    device["trusted"] = _parse_bt_bool(info_line.split(":", 1)[1])
                elif info_line.startswith("Connected:"):
                    device["connected"] = _parse_bt_bool(info_line.split(":", 1)[1])
                elif info_line.startswith("RSSI:"):
                    try:
                        device["rssi"] = int(info_line.split(":", 1)[1].strip())
                    except ValueError:
                        device["rssi"] = None
        status["devices"].append(device)

    return status


async def set_bluetooth_settings(settings):
    logger.info("Writing Bluetooth settings")
    await ensure_bluetooth_agent()
    commands = []
    if settings.powered is not None:
        commands.append(f"power {'on' if settings.powered else 'off'}")
    if settings.pairable is not None:
        commands.append(f"pairable {'on' if settings.pairable else 'off'}")
    if settings.discoverable is not None:
        commands.append(f"discoverable {'on' if settings.discoverable else 'off'}")
    if not commands:
        return
    retval, output = await _bluetoothctl(*commands)
    if retval != 0:
        logger.warning(f"Bluetooth settings failed: {output}")


async def start_bluetooth():
    await ensure_bluetooth_agent()
    retval, output = await _bluetoothctl("power on")
    if retval != 0:
        logger.warning(f"Bluetooth start failed: {output}")


async def stop_bluetooth():
    await ensure_bluetooth_agent()
    retval, output = await _bluetoothctl("power off")
    if retval != 0:
        logger.warning(f"Bluetooth stop failed: {output}")


async def start_bluetooth_scan():
    await ensure_bluetooth_agent()
    if not await _bt_agent_write("scan on"):
        logger.warning("Bluetooth scan start failed: unable to write scan command")


async def stop_bluetooth_scan():
    await ensure_bluetooth_agent()
    if not await _bt_agent_write("scan off"):
        logger.warning("Bluetooth scan stop failed: unable to write scan command")


async def bluetooth_device_action(mac, action):
    await ensure_bluetooth_agent()
    if not re.match(r"^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}$", mac):
        logger.warning(f"Invalid Bluetooth MAC: {mac}")
        return False
    allowed = {
        "pair": f"pair {mac}",
        "trust": f"trust {mac}",
        "connect": f"connect {mac}",
        "disconnect": f"disconnect {mac}",
        "remove": f"remove {mac}",
        "cancel-pairing": f"cancel-pairing {mac}",
    }
    if action not in allowed:
        return False
    retval, output = await _bluetoothctl(allowed[action])
    if retval != 0:
        logger.warning(f"Bluetooth {action} failed for {mac}: {output}")
    return retval == 0


async def bluetooth_pairing_response(accept):
    global BT_AGENT_PENDING
    await ensure_bluetooth_agent()
    ok = await _bt_agent_write("yes" if accept else "no")
    BT_AGENT_PENDING = None
    return ok

async def write_license(type_id, expiration_date):
    #TODO write, needs the signed string
    logger.info("Writing license")
    with open(LICENSE_FILE, 'w+') as f:
        f.write(f"{expiration_date},{type_id}")
    retval, _ = await utils.shell("ttnedaemon restart")
    if retval != 0:
        logger.error("Can not restart TycheTools damemon")

async def read_license() -> str:
    #TODO: this should be done at the beginning, thus function should return a global variable
    #TODO: if the license changes, a reboot must be done
    logger.info("Reading license")
    if not os.path.isfile(LICENSE_FILE):
        return "A1"

    with open(LICENSE_FILE, 'r+') as f:
        license_line = f.readline()

    license_data = pickle.loads(base64.b64decode(license_line.encode()))
    license_text = license_data["license"]
    license_sign = license_data["signature"]

    with open("/usr/share/usb_autorun/public.pem", "rb") as key_file:
        public_key = serialization.load_pem_public_key(
                key_file.read(),
                backend=default_backend()
        )
    try:
        public_key.verify(license_sign, license_text.encode(),
                padding.PKCS1v15(), hashes.SHA256()
        )
    except:
        return "A1"

    line_split = license_text.split(',', 3)
    sn = line_split[0]
    license_type = line_split[2]
    epoch_exp = int(line_split[1])
    epoch_now = int(time.time())
    logger.info(f"License expiration time: {epoch_exp} (current epoch: {epoch_now})")
    logger.info(f"License type: {license_type}, SN: {sn}")
    if epoch_exp < epoch_now:
        logger.warning("License has expired")
        return "A1"
    cm_sn, _ = read_snpn()
    if cm_sn != sn:
        logger.warning("License not valid for this CM, invalid serial number")
        return "A1"
    return license_type

async def start_ssh():
    logger.info("Starting SSH...")
    ssh, snmp, modbus = await nw_functions.read_services()
    if ssh:
        logger.warning("SSH alredy started")
        return
    await nw_functions.write_services(1, snmp, modbus)
    retval, _ = await utils.shell("/etc/init.d/sshd start")
    if retval != 0:
        logger.warning("Can not start SSH")

async def stop_ssh():
    logger.info("Stopping SSH...")
    ssh, snmp, modbus = await nw_functions.read_services()
    if not ssh:
        logger.warning("SSH alredy stopped")
        return
    await nw_functions.write_services(0, snmp, modbus)
    retval, _ = await utils.shell("/etc/init.d/sshd stop")
    if retval != 0:
        logger.warning("Can not stop SSH")

async def start_snmp():
    logger.info("Starting SNMP...")
    ssh, snmp, modbus = await nw_functions.read_services()
    if snmp:
        logger.warning("SNMP alredy started")
        return
    await nw_functions.write_services(ssh, 1, modbus)
    os.makedirs("/home/root/snmp", exist_ok=True)
    retval, _ = await utils.shell("cp /usr/share/ttsnmp/ne_snmpd.conf /home/root/snmp/snmpd.conf")
    if retval != 0:
        logger.warning("Can not copy SNMP configuration file")
    retval, _ = await utils.shell("/etc/init.d/snmpd start")
    if retval != 0:
        logger.warning("Can not start SNMP")

async def stop_snmp():
    logger.info("Stopping SNMP...")
    ssh, snmp, modbus = await nw_functions.read_services()
    if not snmp:
        logger.warning("SNMP alredy stopped")
        return
    await nw_functions.write_services(ssh, 0, modbus)
    retval, _ = await utils.shell("/etc/init.d/snmpd stop")
    if retval != 0:
        logger.warning("Can not stop SNMP")
        return

async def start_modbus():
    logger.info("Starting Modbus...")
    ssh, snmp, modbus = await nw_functions.read_services()
    if modbus:
        logger.warning("Modbus alredy started")
        return
    await nw_functions.write_services(ssh, snmp, 1)
    retval, _ = await utils.shell("/etc/init.d/modbus_server start")
    if retval != 0:
        logger.warning("Can not start Modbus")

async def stop_modbus():
    logger.info("Stopping Modbus...")
    ssh, snmp, modbus = await nw_functions.read_services()
    if not modbus:
        logger.warning("Modbus alredy stopped")
        return
    await nw_functions.write_services(ssh, snmp, 0)
    retval, _ = await utils.shell("/etc/init.d/modbus_server stop")
    if retval != 0:
        logger.warning("Can not stop Modbus")

async def write_modbus(addr: int):
    logger.info(f"Writing Modbus address ({addr})")
    with open(MODBUS_FILE, 'w+') as f:
        f.write(f"{addr}")

async def read_modbus() -> int:
    logger.info("Reading Modbus address")
    if not os.path.isfile(MODBUS_FILE):
        return -1
    with open(MODBUS_FILE, 'r+') as f:
        line = f.readline()
        if line[-1] == "\n":
            line = line[:-1]
        addr = int(line)
        logger.info(f"Modbus address: {addr}")
        return addr
    return -1


# Update Status Management
UPDATE_CONFIG_FILE = "/home/root/.ne/update_config"
UPDATE_STATUS_FILE = "/home/root/.ne/update_status"
REMOTE_UPDATE_DIR = "/var/lib/pdu_update"
REMOTE_PENDING_FILE = os.path.join(REMOTE_UPDATE_DIR, "pending_fw.bin")
REMOTE_PENDING_METADATA = os.path.join(REMOTE_UPDATE_DIR, "pending_metadata.json")
BLUETOOTH_CONFIG_FILE = "/home/root/.ne/bluetooth_config"
DEFAULT_AUTO_UPDATE = True
DEFAULT_BLUETOOTH_POWERED = True


def _read_update_config():
    """Read auto_update flag and update_server from config file"""
    auto_update = DEFAULT_AUTO_UPDATE
    update_server = ""
    if os.path.isfile(UPDATE_CONFIG_FILE):
        try:
            with open(UPDATE_CONFIG_FILE, 'r') as f:
                lines = f.readlines()
                if len(lines) > 0:
                    auto_update = lines[0].strip().lower() == "true"
                if len(lines) > 1:
                    update_server = lines[1].strip()
        except Exception as e:
            logger.error(f"Error reading update config: {e}")
    return auto_update, update_server


def _write_update_config(auto_update, server):
    """Write auto_update flag and update_server to config file"""
    try:
        os.makedirs(os.path.dirname(UPDATE_CONFIG_FILE), exist_ok=True)
        with open(UPDATE_CONFIG_FILE, 'w') as f:
            f.write("true\n" if auto_update else "false\n")
            f.write(server + "\n")
        logger.info(f"Update config written: auto_update={auto_update}, server={server}")
    except Exception as e:
        logger.error(f"Error writing update config: {e}")


def _is_update_pending():
    """Check if web/UI update is pending"""
    return os.path.isfile(UPDATE_STATUS_FILE)


def _has_remote_update_pending():
    """Check if remote Drive update is pending"""
    return os.path.isfile(REMOTE_PENDING_FILE)


def _remove_remote_update_pending():
    """Remove remote pending update artifacts"""
    try:
        if os.path.isfile(REMOTE_PENDING_FILE):
            os.remove(REMOTE_PENDING_FILE)
            logger.info("Removed remote pending firmware file")
        if os.path.isfile(REMOTE_PENDING_METADATA):
            os.remove(REMOTE_PENDING_METADATA)
            logger.info("Removed remote pending metadata file")
    except Exception as e:
        logger.error(f"Error removing remote pending update: {e}")


def _set_update_pending(pending):
    """Mark web/UI update as pending or clear pending status"""
    try:
        os.makedirs(os.path.dirname(UPDATE_STATUS_FILE), exist_ok=True)
        if pending:
            with open(UPDATE_STATUS_FILE, 'w') as f:
                f.write("true")
            logger.info("Update marked as pending")
        else:
            if os.path.isfile(UPDATE_STATUS_FILE):
                os.remove(UPDATE_STATUS_FILE)
            logger.info("Update pending status cleared")
    except Exception as e:
        logger.error(f"Error setting update pending status: {e}")


def get_update_status():
    """Get current update status"""
    ui_pending = _is_update_pending()
    remote_pending = _has_remote_update_pending()
    auto_update, update_server = _read_update_config()
    is_pending = ui_pending or remote_pending
    prompt = remote_pending
    pending_source = "remote" if remote_pending else ("web" if ui_pending else "")
    logger.info(
        f"Update status: pending={is_pending}, auto_update={auto_update}, server={update_server}, prompt={prompt}, source={pending_source}"
    )
    return {
        "is_pending": is_pending,
        "auto_update": auto_update,
        "update_server": update_server,
        "prompt": prompt,
        "pending_source": pending_source,
    }


def set_update_settings(auto_update, server):
    """Set auto-update flag and server address"""
    _write_update_config(auto_update, server)
    logger.info(f"Update settings saved: auto_update={auto_update}")


def confirm_update(confirm):
    """Confirm or reject pending update"""
    remote_pending = _has_remote_update_pending()
    if confirm:
        # Execute the update
        logger.info("User confirmed update, executing...")
        if remote_pending:
            utils.schedule_in(5, utils.shell("usb_autorun.sh run " + REMOTE_PENDING_FILE))
        else:
            utils.schedule_in(5, utils.shell("usb_autorun.sh run " + SWUPDATE_FILE))
    else:
        # Reject update
        logger.info("User rejected update")
        if remote_pending:
            _remove_remote_update_pending()
        elif os.path.isfile(SWUPDATE_FILE):
            try:
                os.remove(SWUPDATE_FILE)
                logger.info(f"Removed pending update file: {SWUPDATE_FILE}")
            except Exception as e:
                logger.error(f"Error removing update file: {e}")
    
    _set_update_pending(False)


# Bluetooth Settings Management
def _read_bluetooth_config():
    """Read Bluetooth powered setting from config file"""
    powered = DEFAULT_BLUETOOTH_POWERED
    if os.path.isfile(BLUETOOTH_CONFIG_FILE):
        try:
            with open(BLUETOOTH_CONFIG_FILE, 'r') as f:
                powered = f.read().strip().lower() == "true"
        except Exception as e:
            logger.error(f"Error reading bluetooth config: {e}")
    return powered


def _write_bluetooth_config(powered):
    """Write Bluetooth powered setting to config file"""
    try:
        os.makedirs(os.path.dirname(BLUETOOTH_CONFIG_FILE), exist_ok=True)
        with open(BLUETOOTH_CONFIG_FILE, 'w') as f:
            f.write("true\n" if powered else "false\n")
        logger.info(f"Bluetooth config written: powered={powered}")
    except Exception as e:
        logger.error(f"Error writing bluetooth config: {e}")


async def init_persistent_settings():
    """Initialize persistent settings on startup"""
    logger.info("Initializing persistent settings")
    
    # Ensure defaults are written if files don't exist
    if not os.path.isfile(UPDATE_CONFIG_FILE):
        _write_update_config(DEFAULT_AUTO_UPDATE, "")
    
    if not os.path.isfile(BLUETOOTH_CONFIG_FILE):
        _write_bluetooth_config(DEFAULT_BLUETOOTH_POWERED)
    
    # Apply Bluetooth default if configured
    try:
        bt_powered = _read_bluetooth_config()
        if bt_powered:
            logger.info("Bluetooth configured to be powered on startup")
            await start_bluetooth()
    except Exception as e:
        logger.warning(f"Could not initialize Bluetooth: {e}")
