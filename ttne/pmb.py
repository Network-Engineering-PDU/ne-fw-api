import os
import math
import time
import asyncio
import logging
from packaging import version

from ttne.uart import Uart, UartOpcodes, UartRsp
from ttne.config import config
from ttne.version import PMB_VERSION
from ttne.pic_bootloader import PicBootloader

logger = logging.getLogger(__name__)

# TODO
# class Line:
#     def __init__(self):
#         self.line_id = None
#         self.voltage = None

class Pmb:
    pmb = None

    opcode_to_line = {
        "C": 0,
        "D": 1,
        "E": 2,
        "F": 3,
        "G": 4,
        "H": 5,
    }

    def __init__(self, pdu, uart):
        self.pdu = pdu
        self.uart = uart
        self.measure_flag = False
        self.branch = None
        self.sys_type = None
        self.curr_type = None
        self.data = {}
        for i in range(6):
            self.data[i] = {}
            self.data[i]["v"] = 0
            self.data[i]["i"] = 0
            self.data[i]["p"] = 0
            self.data[i]["q"] = 0
            self.data[i]["s"] = 0
            self.data[i]["pf"] = 0
            self.data[i]["ph"] = 0
            self.data[i]["v_ph"] = 0
            self.data[i]["i_ph"] = 0
            self.data[i]["f"] = 0
            self.data[i]["e"] = 0
            self.data[i]["last_time"] = 0
        self.FW_DIR = "/opt/fw-pmb"
        cmd = UartOpcodes.UART_OP_STOP
        self.uart.send_msg(bytearray(cmd.encode('utf-8')))
        resp, _ = self.get_uart_resp()
        if resp is None:
            logger.error("PMB communication error")

    def _get_switches(self):
        self.uart.clean()
        cmd = UartOpcodes.UART_OP_GET_SW
        self.uart.send_msg(bytearray(cmd.encode('utf-8')))
        resp, data = self.get_uart_resp()
        if resp == None:
            return None
        sw = int(data)
        self.branch = (sw >> 3) & 0b1
        self.sys_type = (sw >> 1) & 0b11
        self.curr_type = sw & 0b1
        self._log_switches(self.branch, self.sys_type, self.curr_type)

    def _log_switches(self, branch, sys_type, curr_type):
        if branch == 0:
            logger.info("Branch: MAIN")
        elif branch == 1:
            logger.info("Branch: MAIN and AUX")
        else:
            logger.error("Branch: ERROR")
        if sys_type == 0:
            logger.info("System type: SINGLE-PHASE")
        elif sys_type == 1:
            logger.info("System type: BI-PHASE")
        elif sys_type == 2:
            logger.info("System type: TRI-PHASE+N")
        elif sys_type == 3:
            logger.info("System type: TRI-PHASE")
        else:
            logger.error("System type: ERROR")
        if curr_type == 0:
            logger.info("Current type: MELEXIS")
        elif curr_type == 1:
            logger.info("Current type: CURRENT TRANSFORMER")
        else:
            logger.error("System type: ERROR")

    async def update_fw(self):
        # This function should be executed before complete initialization and
        # before starting measure task
        pmb_ver = self.get_fw_version()
        logger.info(f"PMB version: {pmb_ver} (required: {PMB_VERSION})")
        if (config.PMB_UPDATE_FORCE or \
                version.parse(PMB_VERSION) > version.parse(pmb_ver)):
            logger.info("Updating PMB")
            bl = PicBootloader(self.uart)
            update_file = None
            for f in os.listdir(self.FW_DIR):
                if f[-4:] == ".hex":
                    update_file = os.path.join(self.FW_DIR, f)
                    break
            if update_file is None:
                logger.error(f"Update file not found")
                return
            await bl.load_hex(update_file)
            self.reset()
            time.sleep(1.5)
            ret = await bl.flash()
            await asyncio.sleep(4)
            if ret:
                new_pmb_ver = self.get_fw_version()
                logger.info(f"PMB updated: {pmb_ver} -> {new_pmb_ver}")
            else:
                logger.error(f"PMB update FAILED")

    def get_pmb_data(self):
        return self.data

    def decode_msg(self, msg):
        msg = msg[1:].split(",")
        opcode = msg[0]
        sync_counter = msg[1]
        msg_data = msg[2]
        if len(msg_data) == 0 or len(opcode) != 1:
            return
        try:
            msg_data = msg_data.split(" ")
            voltage = int(msg_data[0]) / 100
            current = int(msg_data[1]) / 100
            freq = int(msg_data[2]) / 100
            v_ph = int(msg_data[3]) / 100
            i_ph = int(msg_data[4]) / 100
        except:
            logger.error(f"Error decoding message: msg_data = {msg_data}")
            return
        return {"op":opcode, "sync_count": sync_counter,
                "v":voltage, "i":current, "f":freq, "v_ph":v_ph, "i_ph":i_ph}

    def pmb_calc(self, voltage, current, phase, last_time):
        calc_res = {}
        calc_res['p'] = voltage * current * math.cos(math.radians(phase))
        calc_res['q'] = voltage * current * math.sin(math.radians(phase))
        calc_res['s'] = voltage * current
        calc_res['pf'] = math.cos(math.radians(phase))
        current_time = time.monotonic()
        if last_time == 0:
            calc_res['e'] = 0
        else:
            calc_res['e'] = calc_res['p'] * ((current_time - last_time) / 3600) # Wh
        calc_res['last_time'] = current_time
        return calc_res

    def update_data(self, d):
        line_id = Pmb.opcode_to_line[d["op"]]
        line_data = self.data[line_id]
        line_data["v"] = d["v"]
        line_data["i"] = d["i"]
        line_data["f"] = d["f"]
        line_data["v_ph"] = d["v_ph"]
        line_data["i_ph"] = d["i_ph"]
        ph = 0
        if d["i"] != 0:
            ph = d["v_ph"] - d["i_ph"]
            if ph > 180.0:
                ph -= 360.0
            elif ph < -180.0:
                ph += 360.0
        line_data["ph"] = ph
        last_time = line_data["last_time"]
        calc_res = self.pmb_calc(d["v"], d["i"], ph, last_time)
        line_data["last_time"] = calc_res["last_time"]
        line_data["p"] = calc_res["p"]
        line_data["q"] = calc_res["q"]
        line_data["s"] = calc_res["s"]
        line_data["pf"] = calc_res["pf"]
        line_data["e"] += calc_res["e"]
        logger.debug(f"[{d['op']}/L{line_id}]" \
                f"{line_data['v']:.02f}V,{line_data['i']:.02f}A," \
                f"{line_data['f']:.02f}Hz,{line_data['ph']:.02f}deg," \
                f"{line_data['p']:.02f}W,{line_data['q']:.02f}VAr," \
                f"{line_data['s']:.02f}VA,{line_data['pf']:.02f}," \
                f"{line_data['e']:.02f}Wh")
        return line_id

    async def _read(self):
        while self.measure_flag:
            msg = self.uart.readline(timeout=0.1)
            if msg == None or msg == "" or msg[0] != ":":
                if msg != None and msg[0] != ":":
                    pass # For see PMB log
                    # logger.debug(f"pmb_log: {msg}")
                continue
            decoded_data = self.decode_msg(msg)
            line_id = self.update_data(decoded_data)
            # Read all OMs in this line and calc its data
            await asyncio.sleep(0.5) # Wait for OM measure
            om_devices = self.pdu.get_om()
            for om_idx, om in om_devices.items():
                if om.vline_id == line_id:
                    await om.get_metrics()
                    await om.get_fuse()
                    await om.get_connector()
                    pmb_data = self.data[line_id]
                    om.om_calc(pmb_data["v"], pmb_data["f"], pmb_data["v_ph"])
                if decoded_data["op"] == 'C' and om_idx == 0:
                    pmb_sync = decoded_data["sync_count"]
                    om_sync = await om.get_sync_counter()
                    logger.debug(f"SYNC pmb: {pmb_sync} om: {om_sync}")
            await asyncio.sleep(0.1)

    def get_uart_resp(self):
        while True:
            msg = self.uart.readline(timeout=1)
            if msg == None or len(msg) == 0:
                return None, None
            if msg[0] == ':':
                break
        msg = msg[1:].split(",")
        if len(msg) != 2:
            return None, None
        resp = msg[0]
        data = msg[1]
        if len(data) == 0 or len(resp) != 1:
            return None, None
        return resp, data

    def get_fw_version(self):
        self.uart.clean()
        cmd = UartOpcodes.UART_OP_FW_VER
        self.uart.send_msg(bytearray(cmd.encode('utf-8')))
        resp, data = self.get_uart_resp()
        if resp == None:
            logger.error("Error getting PMB firmware version")
            return "0.0.0"
        logger.info(f"PMB FW version: {data} (resp: {resp})")
        return data

    def get_status(self):
        self.uart.clean()
        cmd = UartOpcodes.UART_OP_STATE
        self.uart.send_msg(bytearray(cmd.encode('utf-8')))
        resp, data = self.get_uart_resp()
        state = -1
        if resp != None:
            state = data
            logger.info(f"PMB state: {state} (resp: {resp})")
        return state

    def get_switches(self):
         return {"branch": self.branch, "sys_type": self.sys_type,
                "curr_type": self.curr_type}

    def start_measure(self):
        self.uart.clean()
        cmd = UartOpcodes.UART_OP_START
        self.uart.send_msg(bytearray(cmd.encode('utf-8')))
        resp, data = self.get_uart_resp()
        start = -1
        if resp != None:
            start = data
            logger.info(f"PMB start: {start} (resp: {resp})")
        if resp == UartRsp.UART_RSP_SUCCESS:
            self.measure_flag = True
            asyncio.create_task(self._read())
        return start

    def reset(self):
        self.uart.clean()
        cmd = UartOpcodes.UART_OP_RESET
        self.uart.send_msg(bytearray(cmd.encode('utf-8')))
        resp, data = self.get_uart_resp()
        logger.info(f"PMB reset performed (resp = {resp})")
        return resp == UartRsp.UART_RSP_SUCCESS

    async def stop_measure(self):
        self.measure_flag = False
        await asyncio.sleep(0.5)
        cmd = UartOpcodes.UART_OP_STOP
        self.uart.send_msg(bytearray(cmd.encode('utf-8')))
        await asyncio.sleep(0.5)
        self.uart.clean()
        logger.info(f"PMB stop")
        return 0 #TODO ???
