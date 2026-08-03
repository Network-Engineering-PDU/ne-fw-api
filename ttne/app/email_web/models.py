from typing import List, Literal, Optional

from pydantic import BaseModel, Field, conint, constr, validator


ServerName = constr(
    strip_whitespace=True,
    max_length=253,
    regex=r"^[A-Za-z0-9_.:-]*$",
)
MailAddress = constr(strip_whitespace=True, max_length=254)
Password = constr(max_length=128)


def _validate_mail_address(value: str) -> str:
    if value == "":
        return value
    if any(character.isspace() or ord(character) < 32 for character in value):
        raise ValueError("email addresses cannot contain whitespace")
    local, separator, domain = value.rpartition("@")
    if (not separator or not local or value.count("@") != 1
            or "." not in domain or domain.startswith(".")):
        raise ValueError("invalid email address")
    return value


class EmailWebStoredConfig(BaseModel):
    web_protocol: Literal["http", "https"] = "http"
    web_port: conint(ge=1, le=65535) = 80
    smtp_server: ServerName = ""
    smtp_port: conint(ge=1, le=65535) = 587
    smtp_auth: Literal["none", "login"] = "none"
    from_address: MailAddress = ""
    password: Password = ""
    recipients: List[MailAddress] = Field(default_factory=list)

    _validate_from = validator("from_address", allow_reuse=True)(
        _validate_mail_address
    )

    @validator("recipients")
    def validate_recipients(cls, values):
        if len(values) > 3:
            raise ValueError("at most three recipient addresses are allowed")
        normalized = []
        seen = set()
        for value in values:
            value = _validate_mail_address(value)
            if not value:
                continue
            folded = value.casefold()
            if folded in seen:
                raise ValueError("recipient addresses must be unique")
            seen.add(folded)
            normalized.append(value)
        return normalized


class EmailWebUpdate(BaseModel):
    web_protocol: Literal["http", "https"]
    web_port: conint(ge=1, le=65535)
    smtp_server: ServerName = ""
    smtp_port: conint(ge=1, le=65535)
    smtp_auth: Literal["none", "login"]
    from_address: MailAddress = ""
    password: Optional[Password] = None
    recipients: List[MailAddress] = Field(default_factory=list)

    _validate_from = validator("from_address", allow_reuse=True)(
        _validate_mail_address
    )

    @validator("recipients")
    def validate_recipients(cls, values):
        return EmailWebStoredConfig.validate_recipients(values)


class EmailWebView(BaseModel):
    web_protocol: Literal["http", "https"]
    web_port: int
    smtp_server: str
    smtp_port: int
    smtp_auth: Literal["none", "login"]
    from_address: str
    password_configured: bool
    recipients: List[str]


def view_from_stored(config: EmailWebStoredConfig) -> EmailWebView:
    return EmailWebView(
        web_protocol=config.web_protocol,
        web_port=config.web_port,
        smtp_server=config.smtp_server,
        smtp_port=config.smtp_port,
        smtp_auth=config.smtp_auth,
        from_address=config.from_address,
        password_configured=bool(config.password),
        recipients=config.recipients,
    )
