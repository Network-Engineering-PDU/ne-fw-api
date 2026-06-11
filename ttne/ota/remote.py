"""OTA remote storage backend (GitHub)."""

from typing import Any, Dict

from .github import GitHubClient, GitHubError

RemoteError = GitHubError


def provider_name(cfg: Dict[str, Any]) -> str:
    provider = (cfg.get("provider") or "github_repo").strip().lower()
    if provider == "github":
        return "github_repo"
    return provider


def create_client(cfg: Dict[str, Any]) -> GitHubClient:
    merged = dict(cfg)
    merged["provider"] = provider_name(cfg)
    if merged["provider"] not in ("github_repo", "github_releases"):
        raise ValueError(f"unsupported OTA provider: {merged['provider']}")
    return GitHubClient(merged)


def validate_config(cfg: Dict[str, Any]) -> str:
    """Return an error message when config is incomplete, else empty string."""
    if not cfg.get("enabled", True):
        return ""
    if not cfg.get("github_owner") or not cfg.get("github_repo"):
        return "github_owner and github_repo are required"
    provider = provider_name(cfg)
    if provider not in ("github_repo", "github_releases"):
        return f"unsupported OTA provider: {provider}"
    return ""
