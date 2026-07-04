"""GitHub-hosted firmware: repository files or release assets."""

import base64
import json
import logging
import os
import tempfile
from typing import Any, Callable, Dict, Optional
from urllib.parse import quote

import requests

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"
RAW_BASE = "https://raw.githubusercontent.com"
MEDIA_BASE = "https://media.githubusercontent.com/media"
LFS_POINTER_PREFIX = b"version https://git-lfs.github.com/spec/v1"
FIRMWARE_DOWNLOAD_TIMEOUT = 3600


class GitHubError(Exception):
    pass


class GitHubClient:
    """Download OTA metadata and firmware from a GitHub repo or release."""

    def __init__(self, cfg: Dict[str, Any]):
        self.owner = (cfg.get("github_owner") or "").strip()
        self.repo = (cfg.get("github_repo") or "").strip()
        self.ref = (cfg.get("github_ref") or "main").strip()
        self.path = (cfg.get("github_path") or "").strip().strip("/")
        self.token_path = (cfg.get("github_token_path") or "").strip()
        self.mode = cfg.get("provider", "github")
        if self.mode == "github":
            self.mode = "github_repo"

    def _token(self) -> str:
        if not self.token_path or not os.path.isfile(self.token_path):
            return ""
        with open(self.token_path, "r", encoding="utf-8") as fh:
            return fh.read().strip()

    def _headers(self, accept: str = "application/vnd.github+json") -> Dict[str, str]:
        headers = {
            "Accept": accept,
            "User-Agent": "ttne-ota",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        token = self._token()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def _repo_file_url(self, filename: str) -> str:
        parts = [self.owner, self.repo, self.ref]
        if self.path:
            return f"{RAW_BASE}/{'/'.join(parts)}/{self.path}/{quote(filename)}"
        return f"{RAW_BASE}/{'/'.join(parts)}/{quote(filename)}"

    def _media_file_url(self, filename: str) -> str:
        parts = [self.owner, self.repo, self.ref]
        if self.path:
            return f"{MEDIA_BASE}/{'/'.join(parts)}/{self.path}/{quote(filename)}"
        return f"{MEDIA_BASE}/{'/'.join(parts)}/{quote(filename)}"

    @staticmethod
    def _is_lfs_pointer(path: str) -> bool:
        try:
            with open(path, "rb") as fh:
                return fh.read(64).startswith(LFS_POINTER_PREFIX)
        except OSError:
            return False

    def _api_contents_url(self, filename: str) -> str:
        repo_path = filename if not self.path else f"{self.path}/{filename}"
        return (
            f"{GITHUB_API}/repos/{self.owner}/{self.repo}/contents/"
            f"{quote(repo_path, safe='/')}?ref={quote(self.ref)}"
        )

    def _download_url(self, url: str, destination: str,
            progress_cb: Optional[Callable[[int], None]] = None,
            headers: Optional[Dict[str, str]] = None,
            timeout: int = 120) -> None:
        with requests.get(
            url,
            headers=headers or self._headers(),
            stream=True,
            timeout=timeout,
            allow_redirects=True,
        ) as rsp:
            if not rsp.ok:
                raise GitHubError(f"download failed ({rsp.status_code}): {url}")
            total = int(rsp.headers.get("Content-Length", 0))
            downloaded = 0
            tmp_path = destination + ".part"
            with open(tmp_path, "wb") as fh:
                for chunk in rsp.iter_content(chunk_size=1024 * 256):
                    if not chunk:
                        continue
                    fh.write(chunk)
                    downloaded += len(chunk)
                    if progress_cb and total:
                        progress_cb(int(downloaded * 100 / total))
            os.replace(tmp_path, destination)

    def _download_lfs_object(self, filename: str, destination: str,
            progress_cb: Optional[Callable[[int], None]] = None) -> None:
        media_url = self._media_file_url(filename)
        logger.info("Fetching Git LFS object for %s", filename)
        self._download_url(
            media_url,
            destination,
            progress_cb,
            headers={"User-Agent": "ttne-ota"},
            timeout=FIRMWARE_DOWNLOAD_TIMEOUT,
        )

    def _download_repo_file(self, filename: str, destination: str,
            progress_cb: Optional[Callable[[int], None]] = None) -> None:
        token = self._token()
        if token:
            url = self._api_contents_url(filename)
            self._download_url(
                url, destination, progress_cb,
                headers=self._headers(accept="application/vnd.github.raw"),
                timeout=FIRMWARE_DOWNLOAD_TIMEOUT,
            )
        else:
            url = self._repo_file_url(filename)
            self._download_url(
                url, destination, progress_cb,
                headers={"User-Agent": "ttne-ota"},
                timeout=FIRMWARE_DOWNLOAD_TIMEOUT,
            )
        if self._is_lfs_pointer(destination):
            self._download_lfs_object(filename, destination, progress_cb)

    def _fetch_repo_metadata(self, metadata_name: str) -> Dict[str, Any]:
        url = self._api_contents_url(metadata_name)
        rsp = requests.get(url, headers=self._headers(), timeout=30)
        if not rsp.ok:
            raise GitHubError(
                f"metadata fetch failed ({rsp.status_code}): {rsp.text}")

        data = rsp.json()
        if data.get("encoding") != "base64" or "content" not in data:
            raise GitHubError("metadata response did not include file content")

        try:
            content = base64.b64decode(data["content"]).decode("utf-8")
            return json.loads(content)
        except (ValueError, json.JSONDecodeError) as exc:
            raise GitHubError(f"metadata parse failed: {exc}") from exc

    def _latest_release(self) -> Dict[str, Any]:
        url = f"{GITHUB_API}/repos/{self.owner}/{self.repo}/releases/latest"
        rsp = requests.get(url, headers=self._headers(), timeout=30)
        if rsp.status_code == 404:
            raise GitHubError("no GitHub releases found")
        if not rsp.ok:
            raise GitHubError(f"release lookup failed ({rsp.status_code}): {rsp.text}")
        return rsp.json()

    def _release_asset(self, release: Dict[str, Any], name: str) -> Dict[str, Any]:
        for asset in release.get("assets", []):
            if asset.get("name") == name:
                return asset
        raise GitHubError(f"release asset '{name}' not found")

    def _download_release_asset(self, asset: Dict[str, Any], destination: str,
            progress_cb: Optional[Callable[[int], None]] = None) -> None:
        token = self._token()
        url = asset.get("url") if token else asset.get("browser_download_url")
        if not url:
            raise GitHubError("release asset has no download URL")
        headers = {"User-Agent": "ttne-ota"}
        if token:
            headers = self._headers()
        if token and "api.github.com" in url:
            headers["Accept"] = "application/octet-stream"
        self._download_url(url, destination, progress_cb, headers=headers)

    def fetch_metadata(self, metadata_name: str) -> Dict[str, Any]:
        if not self.owner or not self.repo:
            raise GitHubError("github_owner and github_repo are required")

        if self.mode == "github_releases":
            release = self._latest_release()
            asset = self._release_asset(release, metadata_name)
            with tempfile.NamedTemporaryFile(delete=False) as tmp:
                tmp_path = tmp.name
            try:
                self._download_release_asset(asset, tmp_path)
                with open(tmp_path, "r", encoding="utf-8") as fh:
                    return json.load(fh)
            finally:
                if os.path.isfile(tmp_path):
                    os.remove(tmp_path)

        return self._fetch_repo_metadata(metadata_name)

    def download_firmware(self, firmware_name: str, destination: str,
            progress_cb: Optional[Callable[[int], None]] = None) -> None:
        if not self.owner or not self.repo:
            raise GitHubError("github_owner and github_repo are required")

        if self.mode == "github_releases":
            release = self._latest_release()
            asset = self._release_asset(release, firmware_name)
            self._download_release_asset(asset, destination, progress_cb)
            return

        self._download_repo_file(firmware_name, destination, progress_cb)
