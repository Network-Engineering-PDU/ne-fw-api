import os
import logging
import re
from ttne.config import config

logger = logging.getLogger(__name__)

SNPN_FILE = "/home/root/.ne/sn_pn"

SYS_MONO   = 0
SYS_BI     = 1
SYS_TRI    = 2
SYS_TRI_N  = 3
CURR_MLX   = 0
CURR_TRAFO = 1
BR_MAIN    = 0
BR_BOTH    = 1

PN_PATTERN = re.compile(r"^N[0-9A-Z]{13}$")
INVALID_PN = "N0000000000000"
BASE36_DIGITS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"

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

def _fixed_width(value, width, field_name):
    value = str(value).upper()
    if not value.isalnum() or len(value) > width:
        raise ValueError(
            f"{field_name} must contain at most {width} alpha-numeric characters"
        )
    return value.zfill(width)


def _enum_digit(value, allowed, field_name):
    if isinstance(value, bool) or value not in allowed:
        raise ValueError(f"Invalid {field_name}: {value}")
    return str(value)


def _base36_digit(value):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"Invalid output count: {value}")
    if value < 0 or value >= len(BASE36_DIGITS):
        raise ValueError(f"Output count must be between 0 and 35: {value}")
    return BASE36_DIGITS[value]


def is_valid_pn(pn):
    return (
        isinstance(pn, str)
        and pn != INVALID_PN
        and PN_PATTERN.fullmatch(pn) is not None
    )


# Part-number layout (14 alpha-numeric characters):
# N + BOARDID(6) + REVID(3) + SYSTEM(1) + CURRENT(1) + BRANCH(1) + OUTPUTS(1)
def pn_gen(sys_type, curr_type, n_branch, n_outputs):
    try:
        bid = _fixed_width(config.BOARD_ID, 6, "BOARD_ID")
        rid = _fixed_width(config.REV_ID, 3, "REV_ID")
        system = _enum_digit(sys_type, (SYS_MONO, SYS_BI, SYS_TRI, SYS_TRI_N),
                             "system type")
        current = _enum_digit(curr_type, (CURR_TRAFO, CURR_MLX),
                              "current type")
        branch = _enum_digit(n_branch, (BR_MAIN, BR_BOTH), "branch")
        outputs = _base36_digit(n_outputs)
        pn = f"N{bid}{rid}{system}{current}{branch}{outputs}"
    except (TypeError, ValueError) as exc:
        logger.error("Can not generate PDU part number: %s", exc)
        return INVALID_PN

    if not is_valid_pn(pn):
        logger.error("Generated invalid PDU part number: %s", pn)
        return INVALID_PN
    return pn
