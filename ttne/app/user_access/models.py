from typing import Literal

from pydantic import BaseModel, Field, conlist, constr, root_validator


AccessName = constr(
    strip_whitespace=True,
    min_length=1,
    max_length=24,
    regex=r"^[A-Za-z0-9_. -]+$",
)


class AccessLevel(BaseModel):
    name: AccessName
    capacity: Literal["readOnly", "control", "fullEdit"]


class UserEntry(BaseModel):
    name: AccessName
    level: AccessName


class UserAccessConfig(BaseModel):
    users: conlist(UserEntry, max_items=16) = Field(default_factory=list)
    levels: conlist(AccessLevel, min_items=1, max_items=8)

    @root_validator
    def validate_relationships(cls, values):
        users = values.get("users") or []
        levels = values.get("levels") or []
        level_names = [level.name.casefold() for level in levels]
        user_names = [user.name.casefold() for user in users]
        if len(level_names) != len(set(level_names)):
            raise ValueError("access level names must be unique")
        if len(user_names) != len(set(user_names)):
            raise ValueError("user names must be unique")
        available = set(level_names)
        if any(user.level.casefold() not in available for user in users):
            raise ValueError("every user must reference an existing level")
        if not any(level.capacity == "fullEdit" for level in levels):
            raise ValueError("at least one full-edit level is required")
        return values
