from random import uniform
import logging
from packaging import version

from typing import List, Union

from fastapi import APIRouter, Response

from . import models
from ttne.server import PDU
from ttne.input_power import correct_input_measurements

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
    if pmb is None:
        logger.warning("PMB not initialized")
        return 0
    resp = pmb.get_status()
    return resp

@router.get("/fw-version")
async def get_fw_version() -> Union[models.InputFwVersion, None]:
    pmb = PDU.get_pmb()
    if pmb is None:
        logger.warning("PMB not initialized")
        return models.InputFwVersion(major=0, minor=0, fix=0)
    fw_ver = version.parse(pmb.get_fw_version())
    logger.info(f"PMB FW version: {str(fw_ver)}")
    return models.InputFwVersion(major=fw_ver.major, minor=fw_ver.minor,
            fix=fw_ver.micro)

@router.get("/switches")
async def get_switches() -> Union[models.InputSw, None]:
    pmb = PDU.get_pmb()
    if pmb is None:
        logger.warning("PMB not initialized, returning default switches configuration")
        return models.InputSw(branch=0, sys_type=0, curr_type=0)
    sw = pmb.get_switches()
    return models.InputSw(
            branch=sw["branch"],
            sys_type=sw["sys_type"],
            curr_type=sw["curr_type"])

@router.get("/start")
async def start_measure() -> int:
    pmb = PDU.get_pmb()
    if pmb is None:
        logger.warning("PMB not initialized, cannot start measurements")
        return 1
    resp = pmb.start_measure()
    return resp

@router.get("/stop")
async def stop_measure() -> int:
    pmb = PDU.get_pmb()
    if pmb is None:
        logger.warning("PMB not initialized, cannot stop measurements")
        return 1
    resp = await pmb.stop_measure()
    return resp

@router.get("/{line_id}/data")
async def get_data(line_id: int,
        response: Response) -> Union[models.InputData, None]:
    if line_id < 0 or line_id > INPUT_NUMBER - 1:
        response.status_code = 404
        return
    pmb = PDU.get_pmb()
    if pmb is None:
        logger.warning("PMB not initialized, returning zero power data")
        return models.InputData(
            voltage=0.0,
            current=0.0,
            active_power=0.0,
            reactive_power=0.0,
            apparent_power=0.0,
            power_factor=0.0,
            phase=0.0,
            frequency=0.0,
            energy=0.0,
        )
    data = pmb.get_pmb_data()[line_id]

    (
        voltage,
        current,
        active_power,
        reactive_power,
        apparent_power,
        power_factor,
        phase,
        energy,
    ) = correct_input_measurements(
        data["v"],
        data["i"],
        data["ph"],
        data["p"],
        data["q"],
        data["s"],
        data["pf"],
        data["e"],
    )

    return models.InputData(
        voltage=voltage,
        current=current,
        active_power=active_power,
        reactive_power=reactive_power,
        apparent_power=apparent_power,
        power_factor=power_factor,
        phase=phase,
        frequency=data["f"],
        energy=energy,
    )
