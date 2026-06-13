"""OTA update workflow: check, download, verify, install."""

import hashlib
import logging
import os
import subprocess
import threading
from typing import Any, Dict

from ttne.app.settings import functions as settings_functions
from ttne.config import Config
from ttne.update.coordinator import UpdateCoordinator, UpdateSource

from . import config as ota_config
from . import state as ota_state
from .remote import RemoteError, create_client, validate_config
from .version_compare import is_newer, parse_version

logger = logging.getLogger(__name__)

REQUIRED_METADATA_FIELDS = ("firmware_version", "firmware_file", "sha256")


class OtaUpdater:
    def __init__(self):
        self.cfg = ota_config.load_config()

    def _validate_metadata(self, metadata: Dict[str, Any]) -> None:
        missing = [field for field in REQUIRED_METADATA_FIELDS if field not in metadata]
        if missing:
            raise ValueError(f"metadata missing fields: {', '.join(missing)}")
        parse_version(metadata["firmware_version"])

    def _sha256_file(self, path: str) -> str:
        digest = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _progress(self, percent: int) -> None:
        ota_state.update_state(download_progress=percent)

    def _schedule_installer(self, staging_path: str) -> None:
        cmd = "/usr/bin/usb_autorun.sh run " + staging_path

        def _run():
            subprocess.Popen(
                cmd,
                shell=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.STDOUT,
            )

        threading.Timer(5, _run).start()

    def _pending_version(self) -> str:
        pending_file = os.path.join(ota_state.OTA_DIR, "pending_version")
        try:
            with open(pending_file, "r", encoding="utf-8") as fh:
                return fh.read().strip()
        except OSError:
            return ""

    def _save_pending_metadata(self, metadata: Dict[str, Any]) -> None:
        ota_state.save_pending_metadata(metadata)

    def _load_pending_metadata(self) -> Dict[str, Any]:
        return ota_state.load_pending_metadata()

    def _clear_pending_metadata(self) -> None:
        if os.path.isfile(ota_state.PENDING_METADATA_FILE):
            try:
                os.remove(ota_state.PENDING_METADATA_FILE)
            except OSError as exc:
                logger.warning("Could not remove OTA pending metadata: %s", exc)

    def _save_pending_version(self, version: str) -> None:
        pending_file = os.path.join(ota_state.OTA_DIR, "pending_version")
        os.makedirs(ota_state.OTA_DIR, exist_ok=True)
        with open(pending_file, "w", encoding="utf-8") as fh:
            fh.write(version + "\n")

    def _prepare_pending_update(self, metadata: Dict[str, Any]) -> Dict[str, Any]:
        version = metadata["firmware_version"]
        staging = UpdateCoordinator.ensure_staging_dir(UpdateSource.OTA)

        ok, reason = UpdateCoordinator.begin(
            UpdateSource.OTA, "pending_confirm", firmware_path=staging, version=version)
        if not ok:
            ota_state.update_state(last_error=reason)
            return ota_state.public_view()

        self._save_pending_metadata(metadata)
        self._save_pending_version(version)
        settings_functions._set_update_pending(True)
        ota_state.update_state(
            available_version=version,
            last_check_time=ota_state._utc_now(),
            status="pending_confirm",
            last_error="",
            download_progress=0,
        )
        logger.info("OTA update pending user confirmation on PDU display")
        return ota_state.public_view()

    def _install_pending_update(self) -> Dict[str, Any]:
        metadata = self._load_pending_metadata()
        if not metadata:
            raise ValueError("No pending OTA metadata available")

        firmware_name = metadata["firmware_file"]
        expected_sha = metadata["sha256"].lower()
        staging = UpdateCoordinator.pending_firmware_path()
        if not staging:
            staging = UpdateCoordinator.ensure_staging_dir(UpdateSource.OTA)

        UpdateCoordinator.set_phase("staging", firmware_path=staging)
        ota_state.set_status("downloading", download_progress=0)
        client = create_client(self.cfg)
        client.download_firmware(
            firmware_name,
            staging,
            progress_cb=self._progress,
        )

        ota_state.set_status("verifying")
        actual_sha = self._sha256_file(staging)
        if actual_sha != expected_sha:
            raise ValueError(
                f"SHA256 mismatch (expected {expected_sha}, got {actual_sha})")

        UpdateCoordinator.set_phase("installing", firmware_path=staging)
        ota_state.set_status("installing")
        self._save_pending_version(metadata["firmware_version"])
        self._schedule_installer(staging)
        ota_state.update_state(
            status="pending_reboot",
            available_version=metadata["firmware_version"],
            last_error="",
        )
        self._clear_pending_metadata()
        return ota_state.public_view()

    def _fetch_remote_metadata(self):
        """Download and validate remote metadata.json. Returns (client, metadata)."""
        self.cfg = ota_config.load_config()
        if not self.cfg.get("enabled", True):
            return None, None

        config_error = validate_config(self.cfg)
        if config_error:
            raise ValueError(config_error)

        can_check, reason = UpdateCoordinator.can_check_ota()
        if not can_check:
            raise RuntimeError(reason)

        client = create_client(self.cfg)
        metadata = client.fetch_metadata(self.cfg["metadata_filename"])
        self._validate_metadata(metadata)
        return client, metadata

    def peek_metadata(self) -> Dict[str, Any]:
        """Fetch remote metadata and record versions without downloading firmware."""
        try:
            ota_state.set_status("checking")
            _, metadata = self._fetch_remote_metadata()
            if metadata is None:
                logger.info("OTA disabled in config")
                return ota_state.public_view()

            remote_version = metadata["firmware_version"]
            ota_state.mark_check_complete(available_version=remote_version)
            logger.info("OTA metadata peek: remote version %s", remote_version)
            return ota_state.public_view()
        except (RemoteError, ValueError, OSError, RuntimeError) as exc:
            logger.error("OTA metadata peek failed: %s", exc)
            ota_state.set_status("failed", str(exc))
            return ota_state.public_view()

    def check_for_update(self) -> Dict[str, Any]:
        self.cfg = ota_config.load_config()
        if not self.cfg.get("enabled", True):
            logger.info("OTA disabled in config")
            return ota_state.public_view()

        config_error = validate_config(self.cfg)
        if config_error:
            logger.warning("OTA config incomplete: %s", config_error)
            ota_state.set_status("failed", config_error)
            return ota_state.public_view()

        can_check, reason = UpdateCoordinator.can_check_ota()
        if not can_check:
            logger.info("OTA check deferred: %s", reason)
            current = ota_state.load_state()
            if current.get("status") in (
                "pending_confirm",
                "downloading",
                "verifying",
                "installing",
                "pending_reboot",
            ):
                ota_state.update_state(last_error=reason)
            elif (
                UpdateCoordinator.active_source() == UpdateSource.OTA.value
                and UpdateCoordinator.active_phase() in ("staging", "installing")
            ):
                ota_state.update_state(status="pending_reboot", last_error=reason)
            else:
                ota_state.set_status("idle", reason)
            return ota_state.public_view()

        ota_state.set_status("checking")
        try:
            client, metadata = self._fetch_remote_metadata()
            if metadata is None:
                logger.info("OTA disabled in config")
                return ota_state.public_view()
        except (RemoteError, ValueError, OSError, RuntimeError) as exc:
            logger.error("OTA metadata check failed: %s", exc)
            ota_state.set_status("failed", str(exc))
            return ota_state.public_view()

        installed = settings_functions.get_software_version()
        remote_version = metadata["firmware_version"]
        current_state = ota_state.load_state()

        if not is_newer(remote_version, installed):
            ota_state.mark_check_complete(available_version=remote_version)
            logger.info("OTA up to date (installed=%s remote=%s)", installed, remote_version)
            return ota_state.public_view()

        if (
            current_state.get("status") in ("pending_reboot", "pending_confirm")
            and current_state.get("available_version") == remote_version
        ) or self._pending_version() == remote_version:
            logger.info("OTA update %s already pending", remote_version)
            if current_state.get("status") == "pending_reboot":
                ota_state.mark_pending_reboot(remote_version)
            else:
                ota_state.update_state(status="pending_confirm", available_version=remote_version)
            return ota_state.public_view()

        auto_update, _ = settings_functions._read_update_config()

        allowed, block_reason = UpdateCoordinator.can_begin(UpdateSource.OTA)
        if not allowed:
            logger.info("OTA install deferred: %s", block_reason)
            ota_state.update_state(
                available_version=remote_version,
                last_error=block_reason,
            )
            return ota_state.public_view()

        if auto_update:
            return self._prepare_pending_update(metadata)

        logger.info("OTA update available: %s -> %s", installed, remote_version)
        return self._perform_update(client, metadata)

    def _perform_update(self, client, metadata: Dict[str, Any]) -> Dict[str, Any]:
        firmware_name = metadata["firmware_file"]
        expected_sha = metadata["sha256"].lower()
        staging = UpdateCoordinator.ensure_staging_dir(UpdateSource.OTA)
        version = metadata["firmware_version"]

        ok, reason = UpdateCoordinator.begin(
            UpdateSource.OTA, "staging", firmware_path=staging, version=version)
        if not ok:
            ota_state.update_state(last_error=reason)
            return ota_state.public_view()

        try:
            ota_state.set_status("downloading", download_progress=0)
            client.download_firmware(
                firmware_name,
                staging,
                progress_cb=self._progress,
            )

            ota_state.set_status("verifying")
            actual_sha = self._sha256_file(staging)
            if actual_sha != expected_sha:
                raise ValueError(
                    f"SHA256 mismatch (expected {expected_sha}, got {actual_sha})")

            ota_state.set_status("installing")
            self._save_pending_version(version)
            self._install_firmware(staging, version)
            return ota_state.public_view()
        except Exception as exc:
            logger.error("OTA update failed: %s", exc)
            if os.path.isfile(staging):
                try:
                    os.remove(staging)
                except OSError:
                    pass
            UpdateCoordinator.end(UpdateSource.OTA, success=False)
            ota_state.set_status("failed", str(exc), download_progress=0)
            return ota_state.public_view()

    def _install_firmware(self, staging_path: str, new_version: str) -> None:
        """Install firmware using the existing signed update pipeline."""
        UpdateCoordinator.set_phase("installing", firmware_path=staging_path)
        self._schedule_installer(staging_path)
        ota_state.update_state(status="pending_reboot", available_version=new_version)

    def run_pending_update(self) -> Dict[str, Any]:
        self.cfg = ota_config.load_config()
        try:
            return self._install_pending_update()
        except Exception as exc:
            logger.error("OTA pending update failed: %s", exc)
            UpdateCoordinator.end(UpdateSource.OTA, success=False)
            ota_state.set_status("failed", str(exc), download_progress=0)
            return ota_state.public_view()


def run_check() -> Dict[str, Any]:
    return OtaUpdater().check_for_update()


def run_peek() -> Dict[str, Any]:
    return OtaUpdater().peek_metadata()
