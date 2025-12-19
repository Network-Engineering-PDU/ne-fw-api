import logging

import asyncio

logger = logging.getLogger(__name__)

I2C_WHO = 0x31
I2C_RETRIES = 5

class I2COpcodes:
    I2C_OP_FW_VER_MAJOR = 0x06
    I2C_OP_FW_VER_MINOR = 0x07
    I2C_OP_FW_VER_FIX   = 0x08
    I2C_OP_WHO_AM_I     = 0x09
    I2C_OP_STATE        = 0x10
    I2C_OP_CONN         = 0x11
    I2C_OP_FUSE         = 0x12
    I2C_OP_CURRENT_MSB  = 0x13
    I2C_OP_CURRENT_LSB  = 0x14
    I2C_OP_PHASE_MSB    = 0x15
    I2C_OP_PHASE_LSB    = 0x16
    I2C_OP_RELAY        = 0x17
    I2C_OP_RESET        = 0x18
    I2C_OP_CALIB_XMSB   = 0x19
    I2C_OP_CALIB_MSB    = 0x1A
    I2C_OP_CALIB_LSB    = 0x1B
    I2C_OP_CALIB_XLSB   = 0x1C
    I2C_OP_CALIB_SET    = 0x1D
    I2C_OP_EN_MEASURE   = 0x1E
    I2C_OP_SW_READ      = 0x1F
    I2C_OP_SYNC_C_MSB   = 0x20
    I2C_OP_SYNC_C_LSB   = 0x21

class I2C:
    def __init__(self, bus):
        self.lock = asyncio.Lock()

    def close(self):
        pass

    async def scan(self, start_addr, stop_addr):
        return None

    async def read(self, addr, reg, length):
        return [1]

    async def read_byte(self, addr, reg):
        return 1

    async def write(self, addr, reg, data):
        pass

    async def write_byte(self, addr, reg, byte):
        pass

    async def write_data(self, addr, data):
        pass

    async def read_data(self, addr, count):
        return [1]
