import logging
from datetime import datetime as dt
import asyncio

from ttne.http_helper import HttpHelper
from ttne.config import config
from ttne import utils


logger = logging.getLogger(__name__)

class PduSender:
    PERIOD = 60 # 60s

    def __init__(self, pdu):
        self.pdu = pdu
        self.http = HttpHelper()
        self.counter = 0

    def start(self):
        self.pdu_task = utils.periodic_task(self.send, PduSender.PERIOD)

    def stop(self):
        if self.pdu_task:
            self.pdu_task.cancel()

    async def send(self):
        await asyncio.sleep(1)
        url = f"http://{config.NE_IP}:{config.NE_PORT}/api/pdu-data/"
        body = {
            "datetime": dt.now().strftime("%d/%m/%Y %H:%M"),
            "input_lines": [],
            "output_lines": []
        }

        pmb = self.pdu.get_pmb()
        for i in range(6):
            pmb_data = pmb.get_pmb_data()[i]
            input_line = {
                "line_id": i+1,
                "voltage": pmb_data["v"],
                "current": pmb_data["i"],
                "active_power": pmb_data["p"],
                "reactive_power": pmb_data["q"],
                "apparent_power": pmb_data["s"],
                "power_factor": pmb_data["pf"],
                "phase_vi":pmb_data["ph"],
                "frequency": pmb_data["f"],
                "energy": pmb_data["e"],
                "phase_total": 0,
            }
            body["input_lines"].append(input_line)

        om_devices = self.pdu.get_om()
        for om_idx, om in om_devices.items():
            om_data = om.get_data()
            output_line = {
                "line_id": om_idx+1,
                "frequency": om_data["f"],
                "phase_total": 0,
                "phase_vi": om_data["ph"],
                "active_power": om_data["p"],
                "reactive_power": om_data["q"],
                "apparent_power": om_data["s"],
                "energy": om_data["e"],
                "voltage": om_data["v"],
                "current": om_data["i"],
                "power_factor": om_data["pf"]
            }
            body["output_lines"].append(output_line)
        await self.http.request("pdu-data", "POST", url, body)
        self.counter += 1
