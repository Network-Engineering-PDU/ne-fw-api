#!/usr/bin/env python3

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

try:
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseDownload
    GOOGLE_LIBS_AVAILABLE = True
except ImportError:
    GOOGLE_LIBS_AVAILABLE = False

import requests

DEFAULT_CONFIG = {
    "google_drive_folder_id": "",
    "service_account_path": "/etc/pdu_remote_update/service_account.json",
    "metadata_filename": "metadata.json",
    "poll_interval_seconds": 3600,
    "download_timeout_seconds": 300,
    "download_dir": "/var/lib/pdu_update/download",
    "staging_dir": "/var/lib/pdu_update/staging",
    "state_file": "/var/lib/pdu_update/state.json",
    "install_command": ["/usr/bin/swupdate", "-H", "imx7-var-som:1.0", "-i"],
    "reboot_command": ["/sbin/reboot"],
    "ab_partition": False,
    "slot_a_device": "/dev/mmcblk0p2",
    "slot_b_device": "/dev/mmcblk0p3",
    "active_slot_envvar": "rootfs_slot",
    "boot_verify_timeout_seconds": 300,
    "rollback_enabled": True,
    "log_file": "/var/log/pdu_remote_update.log",
    "metadata_url": "",
}

logger = logging.getLogger("remote_drive_updater")


class LocalState:
    def __init__(self, path: Path):
        self.path = path
        self.data = {
            "installed_build_time": "1970-01-01T00:00:00Z",
            "installed_sha256": "",
            "last_checked_at": None,
            "last_update_result": None,
            "pending_update": None,
            "active_slot": None,
            "previous_slot": None,
            "boot_verified": False,
        }
        self._load()

    def _load(self):
        if self.path.is_file():
            try:
                with self.path.open("r", encoding="utf-8") as f:
                    self.data.update(json.load(f))
            except Exception as exc:
                logger.warning("Unable to read state file %s: %s", self.path, exc)

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_file = self.path.with_suffix(".tmp")
        with temp_file.open("w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2, sort_keys=True)
            f.write("\n")
        temp_file.replace(self.path)

    def get_installed_build_time(self) -> datetime:
        return parse_iso8601(self.data["installed_build_time"])

    def set_installed(self, build_time: str, sha256: str):
        self.data["installed_build_time"] = build_time
        self.data["installed_sha256"] = sha256
        self.data["last_update_result"] = "installed"
        self.data["pending_update"] = None
        self.data["boot_verified"] = False
        self.save()

    def set_pending_update(self, metadata: Dict[str, Any], firmware_path: str):
        self.data["pending_update"] = {
            "build_time": metadata["build_time"],
            "sha256": metadata["sha256"],
            "firmware_file": metadata["firmware_file"],
            "firmware_path": firmware_path,
            "staged_at": utc_now(),
        }
        self.data["last_update_result"] = "pending"
        self.data["boot_verified"] = False
        self.save()

    def mark_boot_success(self) -> None:
        pending = self.data.get("pending_update")
        if pending is None:
            logger.info("No pending update to verify on boot")
            return

        build_time = pending.get("build_time")
        sha256 = pending.get("sha256")
        if build_time and sha256:
            self.data["installed_build_time"] = build_time
            self.data["installed_sha256"] = sha256
            self.data["last_update_result"] = "installed"
            logger.info("Remote update boot verified; installed build_time=%s", build_time)
        else:
            logger.warning("Pending update missing build_time or sha256; preserving existing installed metadata")
            self.data["last_update_result"] = "boot_success"

        self.data["pending_update"] = None
        self.data["boot_verified"] = True
        self.save()

    def mark_rejected(self, reason: str):
        self.data["pending_update"] = None
        self.data["last_update_result"] = reason
        self.data["boot_verified"] = False
        self.save()


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso8601(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value)


def compare_build_times(local: str, remote: str) -> int:
    local_dt = parse_iso8601(local)
    remote_dt = parse_iso8601(remote)
    if remote_dt > local_dt:
        return 1
    if remote_dt < local_dt:
        return -1
    return 0


class GoogleDriveClient:
    def __init__(self, folder_id: str, service_account_path: Optional[Path], metadata_filename: str):
        self.folder_id = folder_id
        self.metadata_filename = metadata_filename
        self.service_account_path = service_account_path
        self.service = None
        if folder_id and service_account_path:
            if not GOOGLE_LIBS_AVAILABLE:
                raise RuntimeError("google-api-python-client and google-auth are required for Drive API integration")
            if not service_account_path.is_file():
                raise FileNotFoundError(f"Service account file not found: {service_account_path}")
            creds = Credentials.from_service_account_file(str(service_account_path), scopes=["https://www.googleapis.com/auth/drive.readonly"])
            self.service = build("drive", "v3", credentials=creds, cache_discovery=False)

    def _find_metadata_file_id(self) -> str:
        query = f"'{self.folder_id}' in parents and name = '{self.metadata_filename}' and trashed = false"
        response = self.service.files().list(q=query, fields="files(id,name)").execute()
        files = response.get("files", [])
        if len(files) != 1:
            raise RuntimeError(f"Expected exactly one metadata file named {self.metadata_filename} in folder {self.folder_id}, found {len(files)}")
        return files[0]["id"]

    def fetch_metadata_json(self) -> Dict[str, Any]:
        file_id = self._find_metadata_file_id()
        request = self.service.files().get_media(fileId=file_id)
        with tempfile.TemporaryFile() as fh:
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
            fh.seek(0)
            return json.load(fh)

    def download_firmware_file(self, firmware_file_name: str, target_path: Path) -> Path:
        query = f"'{self.folder_id}' in parents and name = '{firmware_file_name}' and trashed = false"
        response = self.service.files().list(q=query, fields="files(id,name)").execute()
        files = response.get("files", [])
        if len(files) != 1:
            raise RuntimeError(f"Expected exactly one firmware file named {firmware_file_name} in folder {self.folder_id}, found {len(files)}")
        file_id = files[0]["id"]
        request = self.service.files().get_media(fileId=file_id)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        with target_path.open("wb") as fh:
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
        return target_path


class HttpDownloadClient:
    def __init__(self, metadata_url: str):
        self.metadata_url = metadata_url

    def fetch_metadata_json(self) -> Dict[str, Any]:
        response = requests.get(self.metadata_url, timeout=60)
        response.raise_for_status()
        return response.json()

    def download_firmware_file(self, firmware_file_name: str, target_path: Path) -> Path:
        file_url = self.metadata_url.rsplit("/", 1)[0] + "/" + firmware_file_name
        response = requests.get(file_url, timeout=300, stream=True)
        response.raise_for_status()
        target_path.parent.mkdir(parents=True, exist_ok=True)
        with target_path.open("wb") as fh:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    fh.write(chunk)
        return target_path


class RemoteFirmwareUpdater:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.state = LocalState(Path(config["state_file"]))
        self.download_dir = Path(config["download_dir"])
        self.staging_dir = Path(config["staging_dir"])
        self.remote_update_dir = Path(config.get("remote_update_dir", "/var/lib/pdu_update"))
        self.pending_file = self.remote_update_dir / "pending_fw.bin"
        self.pending_metadata_file = self.remote_update_dir / "pending_metadata.json"
        self.folder_id = config["google_drive_folder_id"]
        self.metadata_filename = config["metadata_filename"]
        self.metadata_url = config.get("metadata_url", "")
        self.install_command = config["install_command"]
        self.reboot_command = config["reboot_command"]
        self.ab_partition = config.get("ab_partition", False)
        self.poll_interval = config["poll_interval_seconds"]
        self.download_timeout_seconds = config["download_timeout_seconds"]
        self.rollback_enabled = config.get("rollback_enabled", True)
        self.boot_verify_timeout_seconds = config["boot_verify_timeout_seconds"]
        self.service_account_path = Path(config["service_account_path"]) if config.get("service_account_path") else None
        self._drive_client = self._build_drive_client()

    def _build_drive_client(self):
        if self.folder_id and self.service_account_path:
            return GoogleDriveClient(self.folder_id, self.service_account_path, self.metadata_filename)
        if self.metadata_url:
            return HttpDownloadClient(self.metadata_url)
        raise RuntimeError("Either google_drive_folder_id + service_account_path or metadata_url must be configured")

    def check_for_update(self) -> bool:
        logger.info("Checking remote firmware metadata")
        metadata = self._drive_client.fetch_metadata_json()
        self._validate_metadata(metadata)

        remote_build_time = metadata["build_time"]
        local_build_time = self.state.data.get("installed_build_time")
        compare_result = compare_build_times(local_build_time, remote_build_time)
        self.state.data["last_checked_at"] = utc_now()
        self.state.save()

        if compare_result <= 0:
            logger.info("No newer firmware available: local=%s remote=%s", local_build_time, remote_build_time)
            return False

        if self._pending_update_matches(metadata):
            logger.info("Remote firmware update already pending for build_time=%s", remote_build_time)
            return False

        logger.info("New firmware available: remote build_time=%s > installed build_time=%s", remote_build_time, local_build_time)
        firmware_path = self._download_firmware(metadata)
        if not self._verify_checksum(firmware_path, metadata["sha256"]):
            logger.error("Downloaded firmware checksum mismatch for %s", firmware_path)
            self.state.mark_rejected("checksum_failed")
            return False

        staged_path = self._stage_firmware(firmware_path)
        self._mark_remote_update_pending(metadata, staged_path)
        return True

    def _validate_metadata(self, metadata: Dict[str, Any]):
        if "build_time" not in metadata or "firmware_file" not in metadata or "sha256" not in metadata:
            raise ValueError("metadata.json must contain build_time, firmware_file, and sha256")
        parse_iso8601(metadata["build_time"])
        if not isinstance(metadata["firmware_file"], str) or not metadata["firmware_file"]:
            raise ValueError("metadata.json firmware_file must be a non-empty string")
        if not isinstance(metadata["sha256"], str) or len(metadata["sha256"] ) not in (64, 128):
            raise ValueError("metadata.json sha256 must be a valid hex digest")

    def _download_firmware(self, metadata: Dict[str, Any]) -> Path:
        firmware_file = metadata["firmware_file"]
        target_path = self.download_dir / firmware_file
        logger.info("Downloading firmware file %s to %s", firmware_file, target_path)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        return self._drive_client.download_firmware_file(firmware_file, target_path)

    def _verify_checksum(self, firmware_path: Path, expected_sha256: str) -> bool:
        import hashlib
        hashobj = hashlib.sha256()
        with firmware_path.open("rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                hashobj.update(chunk)
        actual_sha256 = hashobj.hexdigest().lower()
        expected_sha256 = expected_sha256.lower()
        logger.info("Firmware checksum actual=%s expected=%s", actual_sha256, expected_sha256)
        return actual_sha256 == expected_sha256

    def _stage_firmware(self, firmware_path: Path) -> Path:
        self.staging_dir.mkdir(parents=True, exist_ok=True)
        staged_path = self.staging_dir / firmware_path.name
        logger.info("Staging firmware to %s", staged_path)
        shutil.copy2(firmware_path, staged_path)
        return staged_path

    def _pending_update_matches(self, metadata: Dict[str, Any]) -> bool:
        if not self.pending_metadata_file.is_file():
            return False
        try:
            with self.pending_metadata_file.open("r", encoding="utf-8") as f:
                existing = json.load(f)
        except Exception as exc:
            logger.warning("Unable to read remote pending metadata: %s", exc)
            return False
        return (
            existing.get("build_time") == metadata.get("build_time") and
            existing.get("sha256") == metadata.get("sha256") and
            existing.get("firmware_file") == metadata.get("firmware_file")
        )

    def _mark_remote_update_pending(self, metadata: Dict[str, Any], staged_path: Path):
        self.remote_update_dir.mkdir(parents=True, exist_ok=True)
        pending_path = self.pending_file
        if pending_path.exists():
            pending_path.unlink()
        shutil.copy2(staged_path, pending_path)
        with self.pending_metadata_file.open("w", encoding="utf-8") as f:
            json.dump(
                {
                    "build_time": metadata["build_time"],
                    "sha256": metadata["sha256"],
                    "firmware_file": metadata["firmware_file"],
                    "staged_at": utc_now(),
                },
                f,
                indent=2,
                sort_keys=True,
            )
            f.write("\n")
        logger.info(
            "Remote firmware pending: %s build_time=%s",
            pending_path,
            metadata["build_time"],
        )

    def _install_firmware(self, staged_path: Path):
        if self.ab_partition:
            self._install_ab_partition(staged_path)
            return

        install_cmd = list(self.install_command) + [str(staged_path)]
        logger.info("Installing firmware with command: %s", " ".join(install_cmd))
        self._run_command(install_cmd)
        logger.info("Firmware installer returned successfully")
        self._reboot()

    def _install_ab_partition(self, staged_path: Path):
        logger.info("Installing firmware via A/B partition flow")
        current_slot = self.state.data.get("active_slot")
        if current_slot not in ("A", "B"):
            current_slot = "A"
        inactive_slot = "B" if current_slot == "A" else "A"
        device_name = self.config["slot_a_device"] if inactive_slot == "A" else self.config["slot_b_device"]
        logger.info("Writing firmware to inactive slot %s (%s)", inactive_slot, device_name)
        dd_cmd = ["/usr/bin/dd", f"if={staged_path}", f"of={device_name}", "bs=4M", "conv=fsync"]
        self._run_command(dd_cmd)
        logger.info("Set boot target to slot %s", inactive_slot)
        self.state.data["previous_slot"] = current_slot
        self.state.data["active_slot"] = inactive_slot
        self.state.data["pending_update"] = {
            "build_time": self.state.data["pending_update"]["build_time"],
            "firmware_path": str(staged_path),
            "attempted_at": utc_now(),
        }
        self.state.save()
        self._reboot()

    def _run_command(self, command):
        completed = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        logger.info("Command output:\n%s", completed.stdout)
        if completed.returncode != 0:
            raise RuntimeError(f"Command failed: {completed.returncode}")

    def _reboot(self):
        if self.reboot_command:
            logger.info("Rebooting device with %s", self.reboot_command)
            try:
                self._run_command(self.reboot_command)
            except Exception as exc:
                logger.error("Reboot command failed: %s", exc)
                raise
        else:
            logger.warning("No reboot command configured; manual reboot required")

    def run_forever(self):
        while True:
            try:
                self.check_for_update()
            except Exception as exc:
                logger.exception("Update check failed: %s", exc)
            time.sleep(self.poll_interval)

    def mark_boot_success(self):
        logger.info("Marking boot success after update")
        self.state.mark_boot_success()


def load_config(path: Path) -> Dict[str, Any]:
    config = dict(DEFAULT_CONFIG)
    if not path.is_file():
        raise FileNotFoundError(f"Config file not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        config.update(json.load(f))
    return config


def configure_logging(log_file: str) -> None:
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    handler = logging.handlers.RotatingFileHandler(log_file, maxBytes=5 * 1024 * 1024, backupCount=3)
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    root.addHandler(console)


def main():
    parser = argparse.ArgumentParser(description="Remote Google Drive firmware update daemon")
    parser.add_argument("--config", default="/etc/pdu_remote_update/config.json", help="Path to the remote updater config file")
    parser.add_argument("--once", action="store_true", help="Run a single update check and exit")
    parser.add_argument("--boot-verify", action="store_true", help="Mark the last update boot as successful")
    args = parser.parse_args()

    config = load_config(Path(args.config))
    configure_logging(config["log_file"])
    updater = RemoteFirmwareUpdater(config)

    if args.boot_verify:
        updater.mark_boot_success()
        return

    if args.once:
        updater.check_for_update()
        return

    updater.run_forever()


if __name__ == "__main__":
    main()
