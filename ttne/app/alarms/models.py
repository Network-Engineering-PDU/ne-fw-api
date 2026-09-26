from typing import List

from pydantic import BaseModel


class AlarmItem(BaseModel):
    id: str
    code: str
    severity: int  # 1 = warning, 2 = error
    level: str
    path: str
    desc: str
    first_seen: int  # epoch seconds
    ack: bool


class AlarmList(BaseModel):
    alarms: List[AlarmItem]
    unacked: int


class AlarmAck(BaseModel):
    id: str
