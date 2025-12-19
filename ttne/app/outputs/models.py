# pylint: disable=no-name-in-module
from pydantic import BaseModel

class Output(BaseModel):
    line_id: int
    name: str
    socket_type: str
    low_limit: float
    high_limit: float

# class OutputStatusId(BaseModel):
#     line_id: int
#     switch_status: bool

class OutputStatus(BaseModel):
    switch_status: bool

class OutputFwVersion(BaseModel):
    major: int
    minor: int
    fix: int

# FUSE_UNK = 0, /**< Unknown fuse status. */
# FUSE_OK  = 1, /**< Fuse in good condition. */
# FUSE_NOK = 2, /**< Fuse in bad condition. */
# FUSE_NA  = 3, /**< Fuse not available. */

class OutputData(BaseModel):
    voltage: float
    current: float
    active_power: float
    reactive_power: float
    apparent_power: float
    power_factor: float
    phase: float
    frequency: float
    energy: float
    conn: str
    fuse: int
