import os
import logging
from ttne.config import config

logger = logging.getLogger(__name__)

SNPN_FILE = "/home/root/.ne/sn_pn"

SYS_MONO   = 0
SYS_BI     = 1
SYS_TRI    = 2
SYS_TRI_N  = 3
CURR_TRAFO = 0
CURR_MLX   = 1
BR_MAIN    = 0
BR_BOTH    = 1

def write_snpn(sn, pn):
    logger.info("Writing SN/PN")
    with open(SNPN_FILE, 'w+') as f:
        f.write(f"{sn},{pn}")
    logger.info(f"SN written: {sn}, PN written: {pn})")

def read_snpn():
    logger.info("Reading SN/PN")
    if not os.path.isfile(SNPN_FILE):
        return "N/A", "N/A"
    with open(SNPN_FILE, 'r+') as f:
        line = f.readline()
        if line[-1] == "\n":
            line = line[:-1]
        line_split = line.split(',', 2)
        sn = line_split[0]
        pn = line_split[1]
        logger.info(f"SN readed: {sn}, PN readed: {pn}")
        return sn, pn
    return "N/A", "N/A"

# Serial Number Generator returns a Serial Numer from the given MAC.
def sn_gen( mac):
    if len(mac) != 12:
        return "N/A"
    return mac.upper()

# Part Number Generator returns a Part Numer from the given
# system type (MONO,BI,TRI,TRIN), current measurement type (MLX,TRAFO) and branches
# (MAIN,BOTH). It generates a unique ID and CRC8 for error detection.
def pn_gen(sys_type, curr_type, n_branch):
    if None in (sys_type, curr_type, n_branch):
        logger.error("Can not read PMB configuration for PN generation")
        return "NE0000000000"
    bid = str(config.BOARD_ID).zfill(4)
    rid = str(config.REV_ID).zfill(3)
    sys = str(sys_type)
    curr = str(curr_type)
    branch = str(n_branch)
    pn = f"NE{bid}{rid}{sys}{curr}{branch}"
    return pn
