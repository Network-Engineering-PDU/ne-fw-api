"""Semantic firmware version comparison."""

from packaging.version import InvalidVersion, Version


def parse_version(version_str: str) -> Version:
    """Parse a dotted version string (e.g. 1.2.5)."""
    cleaned = (version_str or "").strip()
    if not cleaned:
        raise InvalidVersion("empty version")
    return Version(cleaned)


def is_newer(remote: str, local: str) -> bool:
    """Return True when remote is strictly newer than local."""
    return parse_version(remote) > parse_version(local)


def is_same_or_older(remote: str, local: str) -> bool:
    """Return True when remote is the same or older than local."""
    return parse_version(remote) <= parse_version(local)
