from fastapi import APIRouter, Response

from . import collector, models

MODULE_NAME = "alarms"

router = APIRouter(
    prefix="/" + MODULE_NAME,
    tags=[MODULE_NAME],
    responses={404: {"description": "Not found", "module": MODULE_NAME}},
)


def _view() -> models.AlarmList:
    alarms = collector.store.snapshot()
    return models.AlarmList(
        alarms=alarms,
        unacked=sum(1 for a in alarms if not a["ack"]),
    )


@router.get("", response_model=models.AlarmList)
async def get_alarms():
    if not collector.store.evaluated:
        await collector.refresh()
    return _view()


@router.post("/ack", response_model=models.AlarmList)
async def post_ack(data: models.AlarmAck, response: Response):
    if not collector.store.ack(data.id):
        response.status_code = 404
    return _view()


@router.post("/ack-all", response_model=models.AlarmList)
async def post_ack_all():
    collector.store.ack_all()
    return _view()
