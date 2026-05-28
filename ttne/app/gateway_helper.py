import json
import asyncio
import logging

from typing import List

import ttgateway.commands as cmds
from ttgateway.config import config

logger = logging.getLogger(__name__)

async def send_cmd(cmd: "ttgateway.command.Command") -> bool:
    try:
        reader, writer = await asyncio.open_unix_connection(config.SERVER_SOCKET)
        writer.write(cmd.serialize())
        await writer.drain()
        rsp_length = int.from_bytes(await reader.read(4), "little")
        rsp_data = await reader.read(rsp_length)
        rsp = json.loads(rsp_data.decode())
        writer.close()
        await writer.wait_closed()
        return rsp
    except Exception as e:
        logger.error(f"Error sending command to gateway: {e}", exc_info=True)
        raise

# TODO: init gateway? -> now in gwrc, but yocto cannot write there
async def start_scan() -> bool:
    try:
        # 1 min timeout and only one node
        cmd = cmds.GatewayStartScan(60, True)
        result = await send_cmd(cmd)
        return result.get("success", False)
    except Exception as e:
        logger.error(f"Failed to start BLE scan: {e}", exc_info=True)
        raise

async def stop_scan() -> bool:
    try:
        cmd = cmds.GatewayStopScan()
        result = await send_cmd(cmd)
        return result.get("success", False)
    except Exception as e:
        logger.error(f"Failed to stop BLE scan: {e}", exc_info=True)
        raise

async def node_list() -> List:
    try:
        cmd = cmds.NodeList()
        result = await send_cmd(cmd)
        return result.get("data", {}).get("node_list", [])
    except Exception as e:
        logger.error(f"Failed to get node list: {e}", exc_info=True)
        return []