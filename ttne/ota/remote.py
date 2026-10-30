"""OTA remote storage backends: GitHub (the default) or any web server.

The update location the user enters (touchscreen or web UI) picks the
backend: empty or a github.com repository address is GitHub, anything else
is a web server folder (IP address or DNS name, optional port and folder).
"""

import re
from typing import Any, Dict, Optional

from . import config as ota_config
from .github import GitHubClient, GitHubError
from .http_server import HttpServerClient, HttpServerError, base_urls

RemoteError = (GitHubError, HttpServerError)

GITHUB_PROVIDERS = ("github_repo", "github_releases")
HTTP_PROVIDER = "http_server"
DEFAULT_SERVER = "https://github.com/{}/{}".format(
    ota_config.DEFAULTS["github_owner"], ota_config.DEFAULTS["github_repo"])

_NAME = r"[A-Za-z0-9_.-]+"
_GITHUB_LOCATION = re.compile(
    rf"^(?:https?://)?(?:www\.)?github\.com/({_NAME})/({_NAME}?)(?:\.git)?"
    rf"(?:/tree/({_NAME})(/[A-Za-z0-9_./-]*)?)?/?$", re.IGNORECASE)


def provider_name(cfg: Dict[str, Any]) -> str:
    provider = (cfg.get("provider") or "github_repo").strip().lower()
    if provider == "github":
        return "github_repo"
    return provider


def github_location(server: str) -> Optional[Dict[str, str]]:
    """Owner, repository, branch and folder of a GitHub address, or None."""
    match = _GITHUB_LOCATION.match((server or "").strip())
    if not match or not match.group(2):
        return None
    return {
        "github_owner": match.group(1),
        "github_repo": match.group(2),
        "github_ref": match.group(3) or "main",
        "github_path": (match.group(4) or "").strip("/"),
    }


def apply_server(cfg: Dict[str, Any], server: str) -> Dict[str, Any]:
    """Points the OTA config at the update location the user entered.
    Raises ValueError for a location that is neither GitHub nor a valid
    server address."""
    server = (server or "").strip()
    cfg = dict(cfg)
    github = github_location(server or DEFAULT_SERVER)
    if github is not None:
        if provider_name(cfg) not in GITHUB_PROVIDERS:
            cfg["provider"] = "github_repo"
        cfg.update(github)
        cfg["server_url"] = ""
        return cfg
    base_urls(server)
    cfg["provider"] = HTTP_PROVIDER
    cfg["server_url"] = server
    return cfg


def is_github(cfg: Dict[str, Any]) -> bool:
    return provider_name(cfg) in GITHUB_PROVIDERS


def create_client(cfg: Dict[str, Any]):
    provider = provider_name(cfg)
    if provider == HTTP_PROVIDER:
        return HttpServerClient(cfg.get("server_url", ""))
    if provider not in GITHUB_PROVIDERS:
        raise ValueError(f"unsupported OTA provider: {provider}")
    merged = dict(cfg)
    merged["provider"] = provider
    return GitHubClient(merged)


def validate_config(cfg: Dict[str, Any]) -> str:
    """Return an error message when config is incomplete, else empty string."""
    if not cfg.get("enabled", True):
        return ""
    provider = provider_name(cfg)
    if provider == HTTP_PROVIDER:
        try:
            base_urls(cfg.get("server_url", ""))
        except ValueError as exc:
            return str(exc)
        return ""
    if provider not in GITHUB_PROVIDERS:
        return f"unsupported OTA provider: {provider}"
    if not cfg.get("github_owner") or not cfg.get("github_repo"):
        return "github_owner and github_repo are required"
    return ""
