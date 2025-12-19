# pylint: disable=no-name-in-module
from pydantic import BaseModel



class Input(BaseModel):
    line_id: int
    low_limit: float
    high_limit: float

class InputSw(BaseModel):
    branch: int
    sys_type: int
    curr_type: int

class InputFwVersion(BaseModel):
    major: int
    minor: int
    fix: int

class InputData(BaseModel):
    voltage: float
    current: float
    active_power: float
    reactive_power: float
    apparent_power: float
    power_factor: float
    phase: float
    frequency: float
    energy: float
