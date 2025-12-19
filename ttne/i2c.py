import logging
from smbus2 import SMBus, i2c_msg

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
        self.i2c = SMBus(bus)

    def close(self):
        #TODO raise exception if self.lock is locked
        self.i2c.close()

    async def scan(self, start_addr, stop_addr):
        devices = []
        async with self.lock:
            for addr in range(start_addr, stop_addr + 1):
                try:
                    who = self.i2c.read_byte_data(addr, 0x09)
                    if who == I2C_WHO: 
                        devices.append(addr)
                except (OSError, BlockingIOError):
                    pass # No device in this address, or device busy
        logger.info(f"I2C devices found: {devices}")
        return devices

    async def read(self, addr, reg, length):
        async with self.lock:
            try:
                wr = i2c_msg.write(addr, [reg])
                rd = i2c_msg.read(addr, length)
                self.i2c.i2c_rdwr(wr, rd)
            except (OSError, BlockingIOError):
                logger.error("I2C read error. Check HW")
        buf = []
        for i in range(length):
            buf.append(rd.buf[i][0])
        return buf

    async def read_byte(self, addr, reg):
        for i in range(I2C_RETRIES):
            async with self.lock:
                try:
                    byte = self.i2c.read_byte_data(addr, reg)
                    return byte
                except (OSError, BlockingIOError):
                    logger.error("I2C read byte error")
            await asyncio.sleep(0.5)
        logger.error("I2C read byte error")
        return None

    async def write(self, addr, reg, data):
        self.write_data(addr, [reg] + data)

    async def write_byte(self, addr, reg, byte):
        for i in range(I2C_RETRIES):
            async with self.lock:
                try:
                    self.i2c.write_byte_data(addr, reg, byte)
                    return
                except (OSError, BlockingIOError):
                    logger.error("I2C write byte error")
            await asyncio.sleep(0.5)
        logger.error("I2C write byte error")

    async def write_data(self, addr, data):
        for i in range(I2C_RETRIES):
            async with self.lock:
                try:
                    wr = i2c_msg.write(addr, data)
                    self.i2c.i2c_rdwr(wr)
                    return
                except (OSError, BlockingIOError):
                    logger.error("I2C write data error")
            await asyncio.sleep(0.5)
        logger.error("I2C write data error")

    async def read_data(self, addr, count):
        for i in range(I2C_RETRIES):
            async with self.lock:
                try:
                    rd = i2c_msg.read(addr, count)
                    self.i2c.i2c_rdwr(rd)
                    buf = []
                    for i in range(length):
                        buf.append(rd.buf[i][0])
                    return buf
                except (OSError, BlockingIOError):
                    logger.warning("I2C write data error")
            await asyncio.sleep(0.5)
        logger.error("I2C write data error")
        return None
