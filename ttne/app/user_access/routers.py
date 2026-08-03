from fastapi import APIRouter

from . import store
from .models import UserAccessConfig


router = APIRouter(prefix="/user-access", tags=["user-access"])


@router.get("", response_model=UserAccessConfig)
async def get_user_access():
    return store.load_config()


@router.put("", response_model=UserAccessConfig)
async def put_user_access(config: UserAccessConfig):
    store.save_config(config)
    return config

