import math 
import logging
from random import uniform
from packaging import version

from typing import Dict, List, Union

from fastapi import APIRouter, Response

from . import models
from ttne.server import PDU

logger = logging.getLogger(__name__)

MODULE_NAME = "outputs"

#TODO: set real connectors
conn_name = {
    -1: "UNKNOWN CONNECTOR",
    0:  "NO CONNECTOR",
    1:  "C10",
    2:  "SCHUKO (rev)",
    4:  "C13",
    8:  "UNIVERSAL (rev)",
}

router = APIRouter(
    prefix="/" + MODULE_NAME,
    tags=[MODULE_NAME],
    responses={404: {"description": "Not found", "module": MODULE_NAME}},
)


@router.get("/")
async def get_outputs() -> List[models.Output]:
    resp = []
    om_devices = PDU.get_om()
    for om_idx, om in om_devices.items():
        state = await om.get_state()
        conn = await om.get_connector()
        if not conn in conn_name:
            conn = -1
        resp.append(
            models.Output(
                status=state,
                line_id=om_idx+1,
                name=f"Output {om_idx+1}",
                socket_type=conn_name[conn],
                low_limit=0.0,
                high_limit=5.0
            )
        )
    return resp

@router.get("/list")
async def get_list():
    return PDU.get_om()

@router.get("/switch-status")
async def get_all_switch_status() -> Union[Dict[int, bool], None]:
    resp = {}
    om_devices = PDU.get_om()
    for i, om in om_devices.items():
        resp[i] = await om.get_relay()
    return resp

@router.get("/{line_id}/fw-version")
async def get_fw_version(line_id: int,
        response: Response) -> Union[models.OutputFwVersion, None]:
    om_devices = PDU.get_om()
    if line_id < 0 or line_id > len(om_devices) - 1:
        response.status_code = 404
        return
    fw_ver_raw = await om_devices[line_id].get_fw_version()
    fw_ver = version.parse(fw_ver_raw)
    logger.debug(f"OM[{line_id}] FW version: {str(fw_ver)}")
    return models.OutputFwVersion(major=fw_ver.major, minor=fw_ver.minor,
            fix=fw_ver.micro)

@router.get("/{line_id}/switch-status")
async def get_switch_status(line_id: int,
        response: Response) -> Union[models.OutputStatus, None]:
    om_devices = PDU.get_om()
    if line_id < 0 or line_id > len(om_devices) - 1:
        response.status_code = 404
        return
    status = await om_devices[line_id].get_relay()
    logger.debug(f"OM[{line_id}] switch-status: {status}")
    return models.OutputStatus(switch_status=status)

@router.put("/{line_id}/switch-status")
async def put_switch_status(line_id: int,
        data: models.OutputStatus, response: Response):
    om_devices = PDU.get_om()
    if line_id < 0 or line_id > len(om_devices) - 1:
        response.status_code = 404
        return
    await om_devices[line_id].set_relay(data.switch_status)
    logger.debug(f"OM[{line_id}] set relay: {data.switch_status}")

@router.get("/{line_id}/data")
async def get_data(line_id: int,
        response: Response) -> Union[models.OutputData, None]:
    om_devices = PDU.get_om()
    if line_id < 0 or line_id > len(om_devices) - 1:
        response.status_code = 404
        return
    om_data = om_devices[line_id].get_data()
    return models.OutputData(
        voltage=om_data["v"],
        current=om_data["i"],
        active_power=om_data["p"],
        reactive_power=om_data["q"],
        apparent_power=om_data["s"],
        power_factor=om_data["pf"],
        phase=om_data["ph"],
        frequency=om_data["f"],
        energy=om_data["e"],
        conn=conn_name[om_data["conn"]],
        fuse=om_data["fuse"],
    )
