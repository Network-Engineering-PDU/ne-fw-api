"""Unified firmware update coordination across web, USB, and OTA channels."""

from .coordinator import UpdateCoordinator, UpdateSource

__all__ = ["UpdateCoordinator", "UpdateSource"]
