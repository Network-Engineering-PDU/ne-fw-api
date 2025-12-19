import json
import asyncio

from typing import List

import ttgateway.commands as cmds
from ttgateway.config import config

async def send_cmd(cmd: "ttgateway.command.Command") -> bool:
    reader, writer = await asyncio.open_unix_connection(config.SERVER_SOCKET)
    writer.write(cmd.serialize())
    await writer.drain()
    rsp_length = int.from_bytes(await reader.read(4), "little")
    rsp_data = await reader.read(rsp_length)
    rsp = json.loads(rsp_data.decode())
    return rsp

# TODO: init gateway? -> now in gwrc, but yocto cannot write there
async def start_scan() -> bool:
    # 1 min timeout and only one node
    cmd = cmds.GatewayStartScan(60, True)
    return (await send_cmd(cmd))["success"]

async def stop_scan() -> bool:
    cmd = cmds.GatewayStopScan()
    return (await send_cmd(cmd))["success"]

async def node_list() -> List:
    cmd = cmds.NodeList()
    return (await send_cmd(cmd))["data"]["node_list"]
