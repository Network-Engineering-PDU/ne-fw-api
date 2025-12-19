from typing import Dict
import asyncio
import logging

import struct

from ttne.dfu_utils import hex_load

CMD_COLON  = b':'
CMD_START  = b'x'
CMD_DATA   = b'y'
CMD_CONFIG = b'v'
CMD_END    = b'z'

MAX_SEND = 64

logger = logging.getLogger(__name__)

class BLUart:
    def __init__(self, uart):
        self.uart = uart

    async def write(self, data):
        self.uart.clean()
        self.uart.send_msg(data)
        ret = await self.recv()
        #TODO timeout?

        return ret == "K"

    async def recv(self):
        colon = False
        retries = 0
        while True:
            msg = self.uart.get_byte(1) # Timeout = 1s
            if msg:
                try:
                    c = msg.decode("utf-8")
                except UnicodeDecodeError:
                    retries += 1
                    if retries == 3:
                        retries = 0
                        logger.error("Can not update PMB")
                        return
                    logger.error("Unicode error")
                    continue
                if c == ":":
                    colon = True
                elif colon:
                    return c

class PicBootloader:
    def __init__(self, uart):
        self.uart = BLUart(uart)
        self.hex_data = None

    def calc_checksum(self, data):
        checksum = sum(data) & 0xFF
        return checksum

    async def send_data(self, addr, data):
        check_data = struct.pack(f"<H{len(data)}s", addr, bytearray(data))
        check = self.calc_checksum(check_data)
        data_tx = struct.pack(f"<sBsH{len(data)}sB",
                CMD_COLON,
                2 + len(data) + 1,
                CMD_DATA,
                addr,
                bytearray(data),
                check)
        return await self.uart.write(data_tx)

    async def load_hex(self, hex_file):
        with open(hex_file) as f:
            app_hex = f.read()

        hex_data = hex_load(app_hex)

        # Remove configuration words if they exist
        hex_data.pop(65528, None)
        hex_data.pop(65529, None)
        hex_data.pop(65530, None)

        #TODO send config at the end

        addrs = list(hex_data.keys())
        addrs.sort()
        self.start_address = addrs[0]
        self.end_address = addrs[-1]
        self.size = self.end_address - self.start_address
        self.hex_data = hex_data

        logger.debug(f"Update size: {self.size}")

    async def flash(self):
        if self.hex_data == None:
            logger.error("No hex data to flash")
            return False

        data_tx = struct.pack("<cBcH", CMD_COLON,  2, CMD_START, self.size)
        ret = await self.uart.write(data_tx)
        if not ret:
            logger.error("Communication error 1")
            return False

        logger.debug("Start sending data")
        for a in range(self.start_address, self.end_address, MAX_SEND):
            send_list = []
            send = False
            for b in range(MAX_SEND):
                addr = a + b
                if addr in self.hex_data:
                    send_list.append(self.hex_data[addr])
                    send = True
                else:
                    send_list.append(0xFF)

            if send:
                ret = await self.send_data(a, send_list)
                if not ret:
                    logger.error("Communication error 2")
                    return False

        data_tx = struct.pack("<sBs", CMD_COLON,  0, CMD_END)
        ret = await self.uart.write(data_tx)

        if not ret:
            logger.error("Communication error 3")
            return False

        return True


