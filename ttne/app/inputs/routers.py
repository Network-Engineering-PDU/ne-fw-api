from random import uniform
import logging
from packaging import version

from typing import List, Union

from fastapi import APIRouter, Response

from . import models
from ttne.server import PDU

MODULE_NAME = "inputs"
INPUT_NUMBER = 6

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/" + MODULE_NAME,
    tags=[MODULE_NAME],
    responses={404: {"description": "Not found", "module": MODULE_NAME}},
)

@router.get("/")
async def get_inputs() -> List[models.Input]:
    resp = []
    for i in range(6):
        resp.append(models.Input(line_id=i+1, low_limit=0.5, high_limit=12.5))
    return resp

@router.get("/status")
async def get_status() -> int: #TODO: change output type
    pmb = PDU.get_pmb()
    resp = pmb.get_status()
    return resp

@router.get("/fw-version")
async def get_fw_version() -> Union[models.InputFwVersion, None]:
    pmb = PDU.get_pmb()
    fw_ver = version.parse(pmb.get_fw_version())
    logger.info(f"PMB FW version: {str(fw_ver)}")
    return models.InputFwVersion(major=fw_ver.major, minor=fw_ver.minor,
            fix=fw_ver.micro)

@router.get("/switches")
async def get_switches() -> Union[models.InputSw, None]:
    pmb = PDU.get_pmb()
    sw = pmb.get_switches()
    return models.InputSw(
            branch=sw["branch"],
            sys_type=sw["sys_type"],
            curr_type=sw["curr_type"])

@router.get("/start")
async def start_measure() -> int:
    pmb = PDU.get_pmb()
    resp = pmb.start_measure()
    return resp

@router.get("/stop")
async def stop_measure() -> int:
    pmb = PDU.get_pmb()
    resp = await pmb.stop_measure()
    return resp

@router.get("/{line_id}/data")
async def get_data(line_id: int,
        response: Response) -> Union[models.InputData, None]:
    if line_id < 0 or line_id > INPUT_NUMBER - 1:
        response.status_code = 404
        return
    pmb = PDU.get_pmb()
    data = pmb.get_pmb_data()[line_id]

    input_data = models.InputData(
        voltage = data["v"],
        current = data["i"],
        active_power = data["p"],
        reactive_power = data["q"],
        apparent_power = data["s"],
        power_factor = data["pf"],
        phase = data["ph"],
        frequency = data["f"],
        energy = data["e"],
    )
    return input_data
