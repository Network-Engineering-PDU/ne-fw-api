import os
import time
import math
import struct
import logging
import asyncio
from packaging import version

from ttne.i2c import I2COpcodes
from ttne.config import config
from ttne.version import OM_VERSION
from ttne.avr_bootloader import AvrBootloader
from ttne.om_line import id_to_vline_tri, id_to_vline_bi

logger = logging.getLogger(__name__)

class Om:
    devices = {}
    n = 0

    def __init__(self, pdu, i2c, addr, om_id):
        self.pdu = pdu
        self.i2c = i2c
        self.addr = addr
        self.id = om_id
        self.data = {}
        self.data["v"] = 0
        self.data["i"] = 0
        self.data["p"] = 0
        self.data["q"] = 0
        self.data["s"] = 0
        self.data["pf"] = 0
        self.data["ph"] = 0
        self.data["i_ph"] = 0
        self.data["f"] = 0
        self.data["e"] = 0
        self.data["sync_count"] = 0
        self.data["conn"] = 0
        self.data["fuse"] = 0
        self.last_time = 0
        self.FW_DIR = "/opt/fw-om"
        self.OM_PHASE_CALIB = 60.0

    @property
    def vline_id(self):
        sw = self.pdu.get_pmb().get_switches()
        sys_type = sw["sys_type"]
        if sys_type == 0b00: # Mono
            return 0
        elif sys_type == 0b01: # Bi
            return id_to_vline_bi[self.id]
        elif sys_type == 0b10 or sys_type == 0b11: # Tri+N and Tri
            return id_to_vline_tri[self.id]

    async def update_fw(self):
        om_ver = await self.get_fw_version() # Array
        logger.info(f"OM version: {om_ver} (required: {OM_VERSION})")
        if (config.OM_UPDATE_FORCE or \
                version.parse(OM_VERSION) > version.parse(om_ver)):
            logger.info(f"Updating OM")
            bl = AvrBootloader(self.i2c)
            update_file = None
            for f in os.listdir(self.FW_DIR):
                if f[-4:] == ".hex":
                    update_file = os.path.join(self.FW_DIR, f)
                    break
            if update_file is None:
                logger.error(f"Update file not found")
                return
            await bl.load_hex(update_file)
            await self.reset()
            time.sleep(1)
            ret = await bl.flash()
            await asyncio.sleep(2)
            if ret:
                new_om_ver = await self.get_fw_version()
                logger.info(f"OM updated: {om_ver} -> {new_om_ver}")
            else:
                logger.error(f"OM update FAILED")
        # Hardcode calibration value
        # await self.set_k(0.04)
        # await self.get_k()

    async def get_fw_version(self):
        om_ver = await self.i2c.read(self.addr,
                I2COpcodes.I2C_OP_FW_VER_MAJOR, 3)
        return ".".join(str(e) for e in om_ver)

    async def get_state(self):
        return await self.i2c.read_byte(self.addr, I2COpcodes.I2C_OP_STATE)

    async def get_connector(self):
        conn = await self.i2c.read_byte(self.addr, I2COpcodes.I2C_OP_CONN)
        self.data["conn"] = conn
        return conn

    async def get_fuse(self):
        fuse = await self.i2c.read_byte(self.addr, I2COpcodes.I2C_OP_FUSE)
        self.data["fuse"] = fuse
        return fuse

    async def get_relay(self):
        resp = await self.i2c.read_byte(self.addr,  I2COpcodes.I2C_OP_RELAY)
        return bool(resp)

    async def set_relay(self, status: bool):
        await self.i2c.write_byte(self.addr, I2COpcodes.I2C_OP_RELAY,
                1 if status else 0)

    async def reset(self):
        await self.i2c.write_byte(self.addr, I2COpcodes.I2C_OP_RESET, 1)

    async def get_current(self):
        resp = await self.i2c.read(self.addr, I2COpcodes.I2C_OP_CURRENT_MSB, 2)
        current = struct.unpack('>H', bytearray(resp)) / 100.0
        return current

    async def get_phase(self):
        resp = await self.i2c.read(self.addr, I2COpcodes.I2C_OP_PHASE_MSB, 2)
        phase = struct.unpack('>H', bytearray(resp)) / 100.0
        return phase

    async def get_sync_counter(self):
        resp = await self.i2c.read(self.addr, I2COpcodes.I2C_OP_SYNC_C_MSB, 2)
        sync_counter, = struct.unpack('>H', bytearray(resp))
        return sync_counter

    async def get_metrics(self):
        resp = await self.i2c.read(self.addr, I2COpcodes.I2C_OP_CURRENT_MSB, 4)
        current, phase = struct.unpack('>HH', bytearray(resp))
        resp = await self.i2c.read(self.addr, I2COpcodes.I2C_OP_SYNC_C_MSB, 2)
        sync_counter, = struct.unpack('>H', bytearray(resp))
        self.data["i"] = current / 100
        self.data["i_ph"] = phase / 100
        self.data["sync_count"] = sync_counter
        return resp

    def get_data(self):
        return self.data

    def om_calc(self, voltage, frequency, v_ph):
        current = self.data['i']
        phase = 0
        if current != 0:
            phase = self.data['i_ph'] - v_ph
            phase += self.OM_PHASE_CALIB
            if phase > 180.0:
                phase -= 360.0
            elif phase < -180.0:
                phase += 360.0
        self.data['ph'] = phase
        self.data['v'] = voltage
        self.data['f'] = frequency
        self.data['p'] = voltage * current * math.cos(math.radians(phase))
        self.data['q'] = voltage * current * math.sin(math.radians(phase))
        self.data['s'] = voltage * current
        self.data['pf'] = math.cos(math.radians(phase))
        current_time = time.monotonic()
        energy = 0
        if self.last_time != 0:
            energy = self.data['p'] * ((current_time - self.last_time) / 3600)
        self.data['e'] += energy
        self.last_time = current_time
        logger.info(f"OM[{self.id}] {self.data['v']}V,{self.data['i']}A," \
                f"{self.data['f']}Hz,{self.data['ph']:.02f}deg," \
                f"{self.data['p']:.02f}W,{self.data['q']:.02f}VAr," \
                f"{self.data['s']:.02f}VA,{self.data['pf']:.02f}," \
                f"{self.data['e']:.02f}Wh")

    async def set_sync(self, enabled: bool):
        await self.i2c.write_byte(self.addr, I2COpcodes.I2C_OP_EN_MEASURE,
                1 if enabled else 0)
        await asyncio.sleep(0.5)

    async def set_k(self, k: float):
        calib_val = struct.pack('>f', k)
        await self.i2c.write(self.addr, I2COpcodes.I2C_OP_CALIB_XMSB,
                list(calib_val))
        await asyncio.sleep(0.5)
        logger.debug(f"SET calibration constant (k = {k}) in addr {self.addr}")

    async def get_k(self) -> float:
        resp = await self.i2c.read(self.addr, I2COpcodes.I2C_OP_CALIB_XMSB, 4)
        k, = struct.unpack('>f', bytearray(resp))
        k = round(k, 4)
        logger.debug(f"GET calibration constant (k = {k}) in addr {self.addr}")
        return k
