from fastapi import APIRouter

from . import store
from .models import DisplayConfig

router = APIRouter(prefix="/display-config", tags=["display-config"])


@router.get("", response_model=DisplayConfig)
async def get_display_config():
    return store.load_config()


@router.put("", response_model=DisplayConfig)
async def put_display_config(config: DisplayConfig):
    # Only the fields sent change, so a client that doesn't know a field
    # (for example the touchscreen language) can't reset it.
    current = store.load_config()
    merged = current.copy(update=config.dict(exclude_unset=True))
    store.save_config(merged)
    return merged
