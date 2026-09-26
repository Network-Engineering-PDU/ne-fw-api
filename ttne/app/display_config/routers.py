from fastapi import APIRouter

from . import store
from .models import DisplayConfig

router = APIRouter(prefix="/display-config", tags=["display-config"])


@router.get("", response_model=DisplayConfig)
async def get_display_config():
    return store.load_config()


@router.put("", response_model=DisplayConfig)
async def put_display_config(config: DisplayConfig):
    store.save_config(config)
    return config
