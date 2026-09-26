# pylint: disable=no-name-in-module
from pydantic import BaseModel, Field, validator

TEXT_FIELDS = (
    "pdu_company", "pdu_rack", "pdu_system", "pdu_ups", "pdu_elec_board",
    "pdu_breaker", "pdu_service",
)


class DisplayConfig(BaseModel):
    """Settings owned by the touchscreen application (cmdisplay)."""

    rotation: int = Field(2, ge=0, le=3)  # 2 = vertical, 3 = horizontal
    inactivity_time: int = Field(5, ge=1, le=300)  # minutes
    skip_login: bool = False
    pdu_company: str = Field("", max_length=255)
    pdu_rack: str = Field("", max_length=255)
    pdu_system: str = Field("", max_length=255)
    pdu_ups: str = Field("", max_length=255)
    pdu_elec_board: str = Field("", max_length=255)
    pdu_breaker: str = Field("", max_length=255)
    pdu_service: str = Field("", max_length=255)

    @validator(*TEXT_FIELDS)
    def _single_line(cls, value):  # noqa: N805
        # The file is line based: a newline would inject another key.
        if "\n" in value or "\r" in value:
            raise ValueError("must be a single line")
        return value.strip()
