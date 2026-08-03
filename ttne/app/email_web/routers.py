from fastapi import APIRouter

from . import store
from .models import (
    EmailWebStoredConfig,
    EmailWebUpdate,
    EmailWebView,
    view_from_stored,
)


router = APIRouter(prefix="/email-web", tags=["email-web"])


@router.get("", response_model=EmailWebView)
async def get_email_web():
    return view_from_stored(store.load_config())


@router.put("", response_model=EmailWebView)
async def put_email_web(update: EmailWebUpdate):
    current = store.load_config()
    password = current.password if update.password is None else update.password
    if update.smtp_auth == "none":
        password = ""
    config = EmailWebStoredConfig(
        **update.dict(exclude={"password"}),
        password=password,
    )
    store.save_config(config)
    return view_from_stored(config)
