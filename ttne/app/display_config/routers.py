from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from . import store, translations
from .models import DisplayConfig

router = APIRouter(prefix="/display-config", tags=["display-config"])
translations_router = APIRouter(prefix="/display-translations",
                                tags=["display-config"])


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


# ---- Touchscreen translation file ---------------------------------------------

def _file_error(ex: translations.TranslationFileError):
    return JSONResponse(status_code=400, content={
        "detail": str(ex), "code": ex.code, "param": ex.detail})


@translations_router.get("")
async def get_display_translations():
    """The translation table in use, as CSV for Excel."""
    try:
        text = translations.export_csv()
    except translations.TranslationFileError as ex:
        return _file_error(ex)
    return Response(content=text.encode("utf-8"), media_type="text/csv",
                    headers={"Content-Disposition":
                             'attachment; filename="touchscreen-translations.csv"'})


@translations_router.get("/info")
async def get_display_translations_info():
    return translations.info()


@translations_router.post("")
async def post_display_translations(request: Request):
    """Checks and stores an uploaded table (the CSV file as the request
    body). The display restarts with it. Returns a report of the texts
    accepted and rejected."""
    data = await request.body()
    try:
        text, report = translations.import_csv(data)
        translations.save_custom(text)
    except translations.TranslationFileError as ex:
        return _file_error(ex)
    store.drop_unknown_language()
    return {"report": report, **translations.info()}


@translations_router.delete("")
async def delete_display_translations():
    """Back to the default texts."""
    translations.reset()
    store.drop_unknown_language()
    return translations.info()
