#!/usr/bin/env python3

import time
import logging
import struct

from ttne.dfu_utils import hex_load

I2C_ADDR = 0x0F

START_CMD = 0x01
DATA_CMD = 0x02
END_CMD = 0x03

logger = logging.getLogger(__name__)

class AvrBootloader:
    def __init__(self, i2c):
        self.i2c = i2c
        self.hex_data = None

    async def send_data(self, addr, data):
        #print ("send:", addr, data)
        data_tx = struct.pack("<BH8s", DATA_CMD, addr, bytearray(data))
        await self.i2c.write_data(I2C_ADDR, data_tx)

    async def load_hex(self, hex_file):
        with open(hex_file) as f:
            app_hex = f.read()

        hex_data = hex_load(app_hex)

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

        data_tx = struct.pack("<BH", START_CMD, self.size)
        try:
            await self.i2c.write_data(I2C_ADDR, data_tx)
            time.sleep(1)
        except OSError:
            logger.error("Bootloader not present in this OM")
            return False

        logger.debug("Start sending data")

        start_address = 8 * int(self.start_address / 8)

        for a in range(start_address, self.end_address, 8):
            send_list = []
            send = False
            for b in range(8):
                addr = a + b
                if addr in self.hex_data:
                    send_list.append(self.hex_data[addr])
                    send = True
                else:
                    send_list.append(0)
            if send:
                await self.send_data(a, send_list)

        data_tx = struct.pack("<B", END_CMD)
        await self.i2c.write_data(I2C_ADDR, data_tx)

        return True


