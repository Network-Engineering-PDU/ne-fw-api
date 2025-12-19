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
    shutil.rmtree("/home/root/.ne/uploads")
    logger.info("Upload directory removed")
    utils.schedule_in(5, utils.shell("usb_autorun.sh run " + SWUPDATE_FILE))

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
    home_dir = os.path.expanduser("~/")
    utils.schedule_in(5,
            utils.shell(f"rm -rf {home_dir}/* {home_dir}/.*; reboot"))

async def start_scan():
    logger.info("Start scan")
    return await gateway_helper.start_scan()

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
