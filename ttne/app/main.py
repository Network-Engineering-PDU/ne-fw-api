import logging
import serial

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ttne import utils
from ttne.app import inputs
from ttne.app import outputs
from ttne.app import settings
from ttne.app import network
from ttne.app.settings import functions as settings_functions
from ttne.network_config import NetworkConfig

from ttne.om import Om
from ttne.pmb import Pmb
from ttne.config import config
logger = logging.getLogger(__name__)

app = FastAPI()

# allows cross-origin requests from Django app
origins = [
    f"http://0.0.0.0:{config.NE_PORT}",
    f"http://{config.NE_IP}:{config.NE_PORT}",
    f"http://127.0.0.1:{config.NE_PORT}",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def init_persistent_settings():
    await settings_functions.init_persistent_settings()
    if config.PLATFORM != "desktop":
        utils.periodic_task(NetworkConfig().repair_ethernet_activation, 5)


app.include_router(inputs.router)
app.include_router(outputs.router)
app.include_router(settings.router)
app.include_router(network.router)
