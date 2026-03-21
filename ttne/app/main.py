import logging
import serial

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ttne.app import inputs
from ttne.app import outputs
from ttne.app import settings
from ttne.app import network

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

app.include_router(inputs.router)
app.include_router(outputs.router)
app.include_router(settings.router)
app.include_router(network.router)


@app.on_event("startup")
async def startup_event():
    """Load auto-update configuration on startup"""
    logger.info("Loading auto-update configuration...")
    await settings.functions.get_auto_update_config()
    logger.info(f"Auto-update enabled: {settings.functions.auto_update_enabled}")
