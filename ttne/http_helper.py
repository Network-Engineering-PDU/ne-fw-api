import time
import json
import asyncio
import logging

import requests

from ttne.config import config


logger = logging.getLogger(__name__)


class HttpHelperConnectionError(Exception):
    pass


class HttpHelper:
    def __init__(self, base_url="", user="", password=""):
        self.base_url = base_url
        self.user = user
        self.password = password
        self.access_token = ""
        self.refresh_token = ""

    def _headers(self, include_auth):
        headers = {
            "content-type": "application/json",
            "user-agent": f"ttgw/{config.VERSION}",
        }
        if include_auth:
            headers["Authorization"] = f"Bearer {self.access_token}"
        return headers


    def _blocking_request(self, name, method, url, body, params, auth, timeout):
        init_ts = time.time()
        try:
            rsp = requests.request(method, url, json=body, params=params,
                headers=self._headers(auth), timeout=timeout)
        except requests.exceptions.ConnectionError:
            if name:
                logger.error(f"HTTP connection error: {name}")
            return None
        except requests.exceptions.ReadTimeout:
            if name:
                logger.error(f"HTTP connection timeout: {name}")
            return None

        if name:
            logger.info("HTTP %s %s rsp status: %d (delay: %d s)", method, name,
                    rsp.status_code, int(time.time() - init_ts))
            logger.debug(rsp.text)
            if not rsp.ok:
                try:
                    data = rsp.json()
                except (json.JSONDecodeError,
                        requests.exceptions.JSONDecodeError):
                    data = rsp.text
                logger.warning(f"HTTP {method} {name} error: {data}")

        return rsp

    async def _request(self, name, method, url, body=None, params=None,
            auth=False, timeout=15):
        return await asyncio.to_thread(self._blocking_request, name, method,
            url, body, params, auth, timeout)

    async def token_verify(self):
        url = f"{self.base_url}/auth/token/verify/"
        body = {"token": self.access_token}
        rsp = await self._request("", "POST", url, body, auth=False)
        if rsp is None:
            raise HttpHelperConnectionError()
        return rsp.ok

    async def token_refresh(self):
        url = f"{self.base_url}/auth/token/refresh/"
        body = {"refresh": self.refresh_token}
        rsp = await self._request("", "POST", url, body, auth=False)
        if rsp is None:
            raise HttpHelperConnectionError()
        if rsp.ok:
            self.access_token = rsp.json()["access"]
        return rsp.ok

    async def token_get(self):
        url = f"{self.base_url}/auth/token/"
        body = {"email": self.user, "password": self.password}
        rsp = await self._request("", "POST", url, body, auth=False)
        if rsp is None:
            raise HttpHelperConnectionError()
        if rsp.ok:
            self.access_token = rsp.json()["access"]
            self.refresh_token = rsp.json()["refresh"]
        return rsp.ok

    async def request(self, name, method, url, body=None, params=None,
            timeout=15):
        if not self.password:
            return await self._request(name, method, url, body, params, False,
                timeout)
        try:
            if not await self.token_verify():
                if not await self.token_refresh():
                    if not await self.token_get():
                        logger.warning("Incorrect HTTP credentials %s", name)
                        return None
            return await self._request(name, method, url, body, params, True,
                timeout)
        except HttpHelperConnectionError:
            logger.warning("Connection error %s", name)
            return None
