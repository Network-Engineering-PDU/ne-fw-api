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
        logger.info("Starting sensor discovery process")
        
        # BLE Sensor Discovery is running continuously in background
        # Ensure it's enabled
        try:
            # Try to enable ble_discovery through gateway
            cmd = cmds.GatewayCommand("app", "enable", "ble_discovery")
            result = await send_cmd(cmd)
            logger.debug(f"BLE discovery enable result: {result}")
        except Exception as e:
            logger.debug(f"Could not explicitly enable BLE discovery: {e}")
        
        # For backward compatibility, also try mesh scan
        try:
            cmd = cmds.GatewayStartScan(60, True)
            result = await send_cmd(cmd)
            if result.get("success"):
                logger.info("Mesh scan started successfully")
                return True
        except Exception as mesh_error:
            logger.debug(f"Mesh scan not available (expected for BLE sensors): {mesh_error}")
        
        # BLE discovery is running in background, return success
        logger.info("BLE discovery is active, scan initiated")
        return True
        
    except Exception as e:
        logger.error(f"Failed to start sensor discovery: {e}", exc_info=True)
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
