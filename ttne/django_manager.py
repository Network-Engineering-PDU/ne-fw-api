import logging
import asyncio
from typing import Any, Dict

logger = logging.getLogger(__name__)

import signal

class DjangoManager:
    def __init__(self):
        self.ne = None

    async def stop(self):
        if self.ne == None:
            return

        try:
            self.ne.send_signal(signal.SIGINT)
            await self.ne.wait()
            logger.info("NE stopped")
        except ProcessLookupError:
            logger.warning("NE process not found")
        
    async def start(self):
        logger.info("Starting NE")
        self.ne = await asyncio.create_subprocess_exec("/usr/bin/python3",
                "/opt/ne/manage.py", "ne_init", stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE)
        logger.info(f"NE created with PID {self.ne.pid}")

        while True:
            line = await self.ne.stdout.readline()
            if not line:
                break
            logger.debug(line.decode().strip())

        ret = await self.ne.wait()
        logger.info(f"NE killed: {ret=}")
