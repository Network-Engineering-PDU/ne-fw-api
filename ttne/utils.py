import os
import time
import logging
import logging.handlers
import threading
import asyncio

from ttne.config import config
from ttne.http_helper import HttpHelper

def periodic_task(function, period, *args, **kwargs):
    logger = logging.getLogger("periodic_task")
    async def periodic_task_coro(function, period, *args, **kwargs):
        next_time = time.time()
        while True:
            next_time += period
            try:
                if asyncio.iscoroutinefunction(function):
                    await asyncio.create_task(function(*args, **kwargs))
                else:
                    function(*args, **kwargs)
            except asyncio.CancelledError:
                return
            except:
                logger.exception(f"Periodic task {function.__name__} ex")
                raise
            await asyncio.sleep(next_time - time.time())
    return asyncio.create_task(periodic_task_coro(function, period, *args,
        **kwargs))

def config_logger(docker=False):
    """ Configures the application logger."""
    os.makedirs(config.TTNE_DIR + "/logs", exist_ok=True)
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(asctime)s - %(name)s - ' +
        '%(levelname)s - %(message)s')
    fh = logging.handlers.RotatingFileHandler(os.path.join(config.TTNE_DIR,
        'logs', "log"), maxBytes=1024*1024*10, backupCount=20000)

    fh.setFormatter(formatter)
    logger.addHandler(fh)
    # Supress third party loggers
    logging.getLogger("urllib3").setLevel(logging.INFO)
    logging.getLogger("websockets").setLevel(logging.INFO)
    logging.getLogger("multipart").setLevel(logging.INFO)

def set_threading_exception_handler():
    threading.excepthook = _threading_exception_handler

def _threading_exception_handler(exc_type, exc_value, exc_traceback):
    """ Function to override the threading exception handler with one
    that logs the exception with logging.
    """
    logger = logging.getLogger("threading")
    logger.error("Uncaught threading exception",
            exc_info=(exc_type, exc_value, exc_traceback))

def schedule_in(delay: int, coro):
    async def _schedule_in():
        await asyncio.sleep(delay)
        await coro
    asyncio.create_task(_schedule_in())


async def read_file(file_path: str) -> str:
    """ Only for small files. """
    def _read_file(file_path):
        try:
            with open(file_path) as f:
                return f.read()
        except (FileNotFoundError, OSError):
            return ""
    return await asyncio.to_thread(_read_file, file_path)


async def write_file(file_path: str, data: str):
    """ Only for small files. """
    def _write_file(file_path, data):
        try:
            with open(file_path, "w") as f:
                f.write(data)
        except OSError:
            pass
    await asyncio.to_thread(_write_file, file_path, data)

async def shell(cmd):
    process = await asyncio.create_subprocess_shell(cmd,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT)
    stdout, _ = await process.communicate()
    retval = await process.wait()
    output = stdout.decode()
    return retval, output