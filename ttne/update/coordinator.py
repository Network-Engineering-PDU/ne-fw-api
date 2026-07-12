"""Mutual exclusion and per-channel staging for firmware updates."""

import json
import logging
import os
import subprocess
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Tuple

from ttne.config import Config

logger = logging.getLogger(__name__)

LOCK_FILE = os.path.join(Config.TTNE_DIR, "update.lock")
SESSION_FILE = os.path.join(Config.TTNE_DIR, "update_session.json")
USB_WORKDIR = "/home/root/autowork"

# Legacy path kept for compatibility; new updates use per-channel staging.
LEGACY_SWUPDATE_FILE = "/home/root/ttfile.bin"


class UpdateSource(str, Enum):
    WEB = "web"
    USB = "usb"
    OTA = "ota"


STAGING_PATHS = {
    UpdateSource.WEB: os.path.join(Config.TTNE_DIR, "updates", "web", "firmware.bin"),
    UpdateSource.OTA: os.path.join(Config.TTNE_DIR, "ota", "downloads", "firmware.bin"),
}


class UpdateCoordinator:
    """Serializes install operations across web, USB, and OTA update channels."""

    @staticmethod
    def staging_path(source: UpdateSource) -> str:
        return STAGING_PATHS[source]

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    @staticmethod
    def _usb_autorun_active() -> bool:
        result = subprocess.run(
            ["pgrep", "-x", "usb_autorun.sh"],
            capture_output=True,
            check=False,
        )
        return result.returncode == 0

    @staticmethod
    def _usb_workdir_active() -> bool:
        if not os.path.isdir(USB_WORKDIR):
            return False
        if os.path.isfile(os.path.join(USB_WORKDIR, "success")):
            return False
        for name in os.listdir(USB_WORKDIR):
            if name in (".", ".."):
                continue
            return True
        return False

    @classmethod
    def _empty_session(cls) -> Dict[str, Any]:
        return {
            "source": "",
            "phase": "idle",
            "firmware_path": "",
            "version": "",
            "started_at": "",
        }

    @classmethod
    def load_session(cls) -> Dict[str, Any]:
        if not os.path.isfile(SESSION_FILE):
            return cls._empty_session()
        try:
            with open(SESSION_FILE, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            logger.error("Failed to read update session: %s", exc)
            return cls._empty_session()
        session = cls._empty_session()
        session.update(data)
        return session

    @classmethod
    def save_session(cls, session: Dict[str, Any]) -> None:
        os.makedirs(os.path.dirname(SESSION_FILE), exist_ok=True)
        tmp = SESSION_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(session, fh, indent=2, sort_keys=True)
            fh.write("\n")
        os.replace(tmp, SESSION_FILE)

    @classmethod
    def clear_session(cls) -> None:
        if os.path.isfile(SESSION_FILE):
            os.remove(SESSION_FILE)

    @classmethod
    def installer_busy(cls) -> bool:
        return cls._usb_autorun_active() or cls._usb_workdir_active()

    @classmethod
    def reconcile_stale_session(cls) -> bool:
        """Drop abandoned session state when the installer is no longer running."""
        session = cls.load_session()
        phase = session.get("phase", "idle")
        if phase in ("idle", "", "pending_confirm"):
            return False
        if session.get("source") == UpdateSource.OTA.value:
            try:
                from ttne.ota import state as ota_state

                if ota_state.load_state().get("status") in (
                    "downloading",
                    "verifying",
                    "installing",
                    "pending_reboot",
                ):
                    return False
            except Exception:
                logger.exception("Could not inspect OTA state while reconciling session")
        if cls.installer_busy():
            return False
        logger.warning(
            "Clearing stale update session (source=%s phase=%s)",
            session.get("source"), phase,
        )
        cls.clear_session()
        return True

    @classmethod
    def active_source(cls) -> str:
        return cls.load_session().get("source", "")

    @classmethod
    def active_phase(cls) -> str:
        return cls.load_session().get("phase", "idle")

    @classmethod
    def public_status(cls) -> Dict[str, Any]:
        cls.reconcile_stale_session()
        session = cls.load_session()
        return {
            "active_update_source": session.get("source", ""),
            "update_phase": session.get("phase", "idle"),
            "update_busy": cls.installer_busy() or session.get("phase") in (
                "staging", "installing",
            ),
        }

    @classmethod
    def can_check_ota(cls) -> Tuple[bool, str]:
        """Return whether OTA may fetch remote metadata (not download/install)."""
        cls.reconcile_stale_session()
        if cls.installer_busy():
            return False, "USB update installer is running"
        return True, ""

    @classmethod
    def can_begin(
        cls,
        source: UpdateSource,
        ignore_installer_busy: bool = False,
    ) -> Tuple[bool, str]:
        cls.reconcile_stale_session()
        if not ignore_installer_busy and cls.installer_busy():
            return False, "USB update installer is running"

        session = cls.load_session()
        active = session.get("source", "")
        phase = session.get("phase", "idle")

        if phase == "idle" or not active:
            return True, ""

        if active == source.value:
            if phase == "pending_confirm":
                return False, f"{source.value} update already awaiting confirmation"
            if phase == "staging":
                return False, f"{source.value} update already in progress"
            return True, ""

        if phase in ("staging", "installing", "pending_confirm"):
            return False, f"{active} update is active ({phase})"

        return True, ""

    @classmethod
    def begin(
        cls,
        source: UpdateSource,
        phase: str,
        firmware_path: str = "",
        version: str = "",
        ignore_installer_busy: bool = False,
    ) -> Tuple[bool, str]:
        allowed, reason = cls.can_begin(source, ignore_installer_busy=ignore_installer_busy)
        if not allowed:
            logger.warning("Cannot begin %s update: %s", source.value, reason)
            return False, reason

        if not firmware_path and source in STAGING_PATHS:
            firmware_path = STAGING_PATHS[source]

        session = {
            "source": source.value,
            "phase": phase,
            "firmware_path": firmware_path,
            "version": version,
            "started_at": cls._utc_now(),
        }
        cls.save_session(session)
        logger.info(
            "Update session started: source=%s phase=%s path=%s",
            source.value, phase, firmware_path,
        )
        return True, ""

    @classmethod
    def set_phase(cls, phase: str, **extra: Any) -> None:
        session = cls.load_session()
        if not session.get("source"):
            return
        session["phase"] = phase
        session.update(extra)
        cls.save_session(session)

    @classmethod
    def end(cls, source: UpdateSource, success: bool = True) -> None:
        session = cls.load_session()
        if session.get("source") not in ("", source.value):
            logger.warning(
                "Ignored end for %s; active source is %s",
                source.value, session.get("source"),
            )
            return

        path = session.get("firmware_path", "")
        if not success and path and source != UpdateSource.USB and os.path.isfile(path):
            try:
                os.remove(path)
            except OSError as exc:
                logger.warning("Could not remove firmware %s: %s", path, exc)

        cls.clear_session()
        logger.info("Update session ended: source=%s success=%s", source.value, success)

    @classmethod
    def pending_firmware_path(cls) -> str:
        session = cls.load_session()
        if session.get("phase") != "pending_confirm":
            return ""
        return session.get("firmware_path", "")

    @classmethod
    def pending_source(cls) -> str:
        session = cls.load_session()
        if session.get("phase") != "pending_confirm":
            return ""
        return session.get("source", "")

    @classmethod
    def ensure_staging_dir(cls, source: UpdateSource) -> str:
        path = cls.staging_path(source)
        os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
        return path

    @classmethod
    def source_from_path(cls, firmware_path: str) -> UpdateSource:
        if "/.ne/updates/web/" in firmware_path:
            return UpdateSource.WEB
        if "/.ne/ota/downloads/" in firmware_path:
            return UpdateSource.OTA
        return UpdateSource.USB

    @classmethod
    def mark_installing(cls, firmware_path: str) -> Tuple[bool, str]:
        source = cls.source_from_path(firmware_path)
        session = cls.load_session()
        active = session.get("source", "")
        if active:
            if active != source.value:
                return False, f"{active} update is active"
            cls.set_phase("installing", firmware_path=firmware_path)
            return True, ""
        return cls.begin(
            source,
            "installing",
            firmware_path=firmware_path,
            ignore_installer_busy=True,
        )

    @classmethod
    def finish_install(cls, firmware_path: str, success: bool) -> None:
        source = cls.source_from_path(firmware_path)
        cls.end(source, success=success)
