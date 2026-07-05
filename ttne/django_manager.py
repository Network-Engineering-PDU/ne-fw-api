import logging
import asyncio
import os

logger = logging.getLogger(__name__)

import signal

class DjangoManager:
    def __init__(self):
        self.ne = None
        self._stopping = False

    async def stop(self):
        self._stopping = True
        if self.ne is None:
            return

        try:
            self.ne.send_signal(signal.SIGINT)
            await asyncio.wait_for(self.ne.wait(), timeout=20)
            logger.info("NE stopped")
        except asyncio.TimeoutError:
            logger.warning("NE did not stop after SIGINT; killing it")
            self.ne.kill()
            await self.ne.wait()
        except ProcessLookupError:
            logger.warning("NE process not found")

    async def _log_output(self, stream):
        while True:
            line = await stream.readline()
            if not line:
                break
            logger.info("NE: %s", line.decode(errors="replace").strip())

    async def start(self):
        while True:
            logger.info("Starting NE")
            self.ne = await asyncio.create_subprocess_exec(
                "/usr/bin/python3",
                "/opt/ne/manage.py",
                "ne_init",
                cwd="/opt/ne",
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            logger.info(f"NE created with PID {self.ne.pid}")

            output_task = asyncio.create_task(self._log_output(self.ne.stdout))
            ret = await self.ne.wait()
            await output_task
            logger.warning(f"NE exited: {ret=}")

            if self._stopping:
                break

            logger.warning("Restarting NE in 5 seconds")
            await asyncio.sleep(5)
