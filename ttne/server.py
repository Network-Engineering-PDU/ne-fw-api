import re 
import os 
import logging
import asyncio
from typing import Any, Dict

import uvicorn

from ttne import utils
from ttne.config import config
from ttne.pdu_sender import PduSender
from ttne.sn_pn_generator import *
from ttne.django_manager import DjangoManager

from ttne.pdu import Pdu
if config.PLATFORM == "desktop":
    from ttne.i2c_desktop import I2C
else:
    from ttne.i2c import I2C

from ttne.uart import Uart

from ttgateway.config import config as gw_config

logger = logging.getLogger(__name__)

PDU = None

LOGGING_CONFIG: Dict[str, Any] = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {
            "()": "uvicorn.logging.DefaultFormatter",
            "fmt": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            "use_colors": None,
        },
    },
    "handlers": {
        "default": {
            "formatter": "default",
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stderr",
        },
        "logfile": {
            "formatter": "default",
            "class": "logging.handlers.RotatingFileHandler",
            "filename": os.path.join(config.TTNE_DIR, "logs", "log"),
        },
    },
    "loggers": {
        "uvicorn": {"handlers": ["logfile"], "level": "INFO", "propagate": False},
        "uvicorn.error": {"handlers": ["default"], "level": "INFO"},
        "uvicorn.access": {"handlers": ["default"], "level": "INFO", "propagate": False},
    },
}

class Server:
    def __init__(self):
        self.server = None
        self.pdu_sender = None
        self.ne = None

    async def init(self):
        if not hasattr(asyncio, "to_thread"): #TODO: Remove when python3.9
            logger.debug("Using custom to_thread function")
            from ttne.to_thread_helper import to_thread
            asyncio.to_thread = to_thread
        os.makedirs(config.TTNE_DIR, exist_ok=True)

    def exit_trap(self):
        logger.warning("Loop not yet initialized. Cannot stop now")
        #TODO create task to wait and send SIGINT

    async def clean_exit(self):
        logger.info("Waiting processes to stop")
        if self.pdu_sender:
            self.pdu_sender.stop()
        await self.ne.stop()
        await asyncio.sleep(1)
        try:
            pmb = PDU.get_pmb()
            await pmb.stop_measure()
            logger.info("PMB measures stopped")
        except:
            logger.error("Uart not present")
            #TODO exit or something??
        await asyncio.sleep(1)
        logger.info("Stoping asyncio")
        self.loop.stop()

    async def start_pdu_sender(self):
        self.pdu_sender = PduSender(PDU)
        self.pdu_sender.start()
        logger.info("PDU sender started")

    async def restart_gateway(self):
        if gw_config.gwrc_file_exists():
            return
        gw_config.create_default_negwrc()
        retval, _ = await utils.shell("ttdaemon restart")
        if retval != 0:
            logger.error("Can not restart TycheTools daemon")
        logger.info("Gateway restarted")

    async def sn_pn(self):
        sn, pn = read_snpn()
        if sn == "N/A" or pn == "N/A":
            mac = "000000000000"
            ret, output = await utils.shell("ip address")
            if ret == 0:
                match = re.search("link/ether ([a-z0-9:]+)", output)
                if match:
                    mac = match.groups()[0]
                    mac = "".join(mac.split(":")).upper()
            sn = sn_gen(mac)
            pmb = PDU.get_pmb()
            sys_type = pmb.get_switches()["sys_type"]
            curr_type = pmb.get_switches()["curr_type"]
            branch = pmb.get_switches()["branch"]
            pn = pn_gen(sys_type, curr_type, branch)
            write_snpn(sn, pn)

    async def start_om(self):
        await asyncio.sleep(2)
        try:
            await PDU.scan_om(I2C(0))
            await PDU.scan_om(I2C(1))
        except:
            logger.error("I2C not present")
            #TODO exit or something??
        om_devices = PDU.get_om()
        for om_idx, om in om_devices.items():
            logger.info(f"OM[{om_idx}] udpate process started")
            await om.update_fw()
        await asyncio.sleep(5)

    async def reset_om(self):
        om_devices = PDU.get_om()
        for om_idx, om in om_devices.items():
            logger.info(f"OM[{om_idx}] reset process")
            await om.reset()
        await asyncio.sleep(2)

    async def start_pmb(self):
        try:
            uart = Uart("/dev/ttymxc4")
            PDU.init_pmb(uart)
            pmb = PDU.get_pmb()
            await pmb.update_fw()
            pmb.reset()
            await asyncio.sleep(5)
            pmb._get_switches()
        except RuntimeError:
            logger.error("Uart not present")
            #TODO exit or something??

    async def start_pmb_measures(self):
        try:
            pmb = PDU.get_pmb()
            logger.debug("Starting PMB measures")
            await asyncio.sleep(5)
            resp = pmb.start_measure()
            if resp != -1:
                logger.info("PMB measures started")
            else:
                logger.error("PMB measures error")
        except:
            logger.error("Uart not present")
            #TODO exit or something??

    async def start_services(self):
        global PDU
        PDU = Pdu()
        await self.init()
        await self.start_om()
        await self.start_pmb()
        await self.sn_pn()
        await self.reset_om()
        await self.start_pmb_measures()
        await self.restart_gateway()

        self.loop.create_task(self.run_server())

        while self.server is None:
            await asyncio.sleep(1)

        await self.server.lifespan.startup_event.wait()

        self.ne = DjangoManager()
        self.loop.create_task(self.ne.start())
        await asyncio.sleep(40) # Wait for NE start
        if config.PLATFORM != "desktop":
            await self.start_pdu_sender()

    async def run_server(self):
        uvicorn_config = uvicorn.Config("ttne.app.main:app",
            host=config.NE_IP, port=config.SERVER_PORT, log_config=LOGGING_CONFIG)
        server = uvicorn.Server(uvicorn_config)
        self.server = server
        await server.serve()
        logger.info("Uvicorn exit")

        # Uvicorn will recive the signal and exits by itself
        await self.clean_exit()

    def run(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.create_task(self.start_services())
        self.loop.run_forever()
        self.loop.close()
