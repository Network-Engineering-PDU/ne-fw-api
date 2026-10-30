"""Firmware on any web server: the update location is an IP address or a
DNS name, with an optional port and folder, holding the same files as the
GitHub repository (metadata.json and the signed ttfile.bin).

Without a scheme HTTPS is tried first, then HTTP: servers on a local network
rarely have certificates. Plain HTTP is safe for the firmware: its SHA-256 is
checked against the metadata and the installer verifies its signature.
"""

import ipaddress
import json
import logging
import os
import re
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import quote, urlsplit

import requests

logger = logging.getLogger(__name__)

METADATA_TIMEOUT = 15
FIRMWARE_DOWNLOAD_TIMEOUT = 3600
MAX_METADATA_BYTES = 64 * 1024
_HOST_LABEL = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")


class HttpServerError(Exception):
    pass


def _valid_host(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        pass
    name = host[:-1] if host.endswith(".") else host
    return bool(name) and len(name) <= 253 and all(
        _HOST_LABEL.fullmatch(label) for label in name.split("."))


def base_urls(location: str) -> List[str]:
    """The URLs to try for a location, in order. Raises ValueError for an
    invalid one."""
    location = (location or "").strip()
    if not location or any(c.isspace() for c in location):
        raise ValueError("Enter the server's IP address or DNS name")
    has_scheme = "://" in location
    parts = urlsplit(location if has_scheme else "https://" + location)
    if parts.scheme not in ("http", "https"):
        raise ValueError("Only http:// and https:// servers are supported")
    if parts.query or parts.fragment or parts.username or parts.password:
        raise ValueError("The location can not have a query, a fragment or a user")
    try:
        port = parts.port
    except ValueError:
        raise ValueError("Invalid port") from None
    host = parts.hostname or ""
    if not _valid_host(host):
        raise ValueError("Invalid IP address or DNS name")
    netloc = f"[{host}]" if ":" in host else host
    if port is not None:
        netloc += f":{port}"
    path = parts.path.rstrip("/")
    schemes = [parts.scheme] if has_scheme else ["https", "http"]
    return [f"{scheme}://{netloc}{path}" for scheme in schemes]


class HttpServerClient:
    """Download OTA metadata and firmware from a web server folder."""

    def __init__(self, location: str):
        self.candidates = base_urls(location)
        self.base = ""      # the URL that answered the metadata request

    def _url(self, base: str, filename: str) -> str:
        return f"{base}/{quote(filename)}"

    @staticmethod
    def _headers() -> Dict[str, str]:
        return {"User-Agent": "ttne-ota"}

    def fetch_metadata(self, metadata_name: str) -> Dict[str, Any]:
        last_error = ""
        for base in self.candidates:
            url = self._url(base, metadata_name)
            try:
                rsp = requests.get(url, headers=self._headers(),
                                   timeout=METADATA_TIMEOUT, stream=True)
            except requests.RequestException as exc:
                # No HTTPS on this server (refused, no certificate...): the
                # next scheme. An explicit scheme has no next one.
                last_error = f"can not reach {url}: {exc.__class__.__name__}"
                logger.info("OTA server: %s", last_error)
                continue
            with rsp:
                if not rsp.ok:
                    raise HttpServerError(
                        f"metadata fetch failed ({rsp.status_code}): {url}")
                content = rsp.raw.read(MAX_METADATA_BYTES + 1, decode_content=True)
            if len(content) > MAX_METADATA_BYTES:
                raise HttpServerError(f"metadata too large: {url}")
            try:
                data = json.loads(content.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise HttpServerError(f"metadata parse failed: {exc}") from exc
            if not isinstance(data, dict):
                raise HttpServerError("metadata is not a JSON object")
            self.base = base
            return data
        raise HttpServerError(last_error or "can not reach the update server")

    def download_firmware(self, firmware_name: str, destination: str,
            progress_cb: Optional[Callable[[int], None]] = None) -> None:
        if os.path.basename(firmware_name) != firmware_name or not firmware_name:
            raise HttpServerError("invalid firmware file name in metadata")
        # The scheme that served the metadata (a pending update downloads
        # with a new client, which tries them again).
        bases = [self.base] if self.base else self.candidates
        last_error = ""
        for base in bases:
            url = self._url(base, firmware_name)
            try:
                rsp = requests.get(url, headers=self._headers(), stream=True,
                                   timeout=FIRMWARE_DOWNLOAD_TIMEOUT)
            except requests.RequestException as exc:
                last_error = f"can not reach {url}: {exc.__class__.__name__}"
                continue
            with rsp:
                if not rsp.ok:
                    raise HttpServerError(
                        f"download failed ({rsp.status_code}): {url}")
                total = int(rsp.headers.get("Content-Length", 0) or 0)
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
            return
        raise HttpServerError(last_error or "can not reach the update server")
