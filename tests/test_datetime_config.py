import asyncio
import calendar
import json
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from ttne import datetime_config, ntp_config
from ttne.app.network import functions as network_functions
from ttne.network_config import NetworkConfig

ZONE_TABLE = (
    "# comment\n"
    "EG\t+3003+03115\tAfrica/Cairo\n"
    "US\t+404251-0740023\tAmerica/New_York\tEastern (most areas)\n"
    "IN\t+2232+08822\tAsia/Kolkata\n"
)


class DateTimeConfigTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        zoneinfo = os.path.join(self.directory.name, "zoneinfo")
        for zone in ("UTC", "Africa/Cairo", "America/New_York", "Asia/Kolkata"):
            os.makedirs(os.path.dirname(os.path.join(zoneinfo, zone)),
                        exist_ok=True)
            open(os.path.join(zoneinfo, zone), "w").close()
        with open(os.path.join(zoneinfo, "zone1970.tab"), "w") as table:
            table.write(ZONE_TABLE)
        self.settings_file = os.path.join(self.directory.name, "datetime.json")
        self.paths = patch.multiple(
            datetime_config,
            DATETIME_SETTINGS_FILE=self.settings_file,
            ZONEINFO_DIR=zoneinfo,
            ZONE_TABLE=os.path.join(zoneinfo, "zone1970.tab"),
            _timezones=None,
        )
        self.paths.start()
        self.ntp_paths = patch.multiple(
            ntp_config,
            NTP_SETTINGS_FILE=os.path.join(self.directory.name, "ntp.json"),
            CHRONY_CONFIG_FILE=os.path.join(self.directory.name, "chrony.conf"),
            NTP_DISABLED_FILE=os.path.join(self.directory.name, "ntp_disabled"),
        )
        self.ntp_paths.start()

    def tearDown(self):
        self.ntp_paths.stop()
        self.paths.stop()
        self.directory.cleanup()

    def test_timezones_and_validation(self):
        self.assertEqual(["Africa/Cairo", "America/New_York", "Asia/Kolkata",
                          "UTC"], datetime_config.timezones())
        self.assertEqual("Asia/Kolkata",
                         datetime_config.validate_timezone("Asia/Kolkata"))
        for invalid in ("", "Mars/Olympus", "../../etc/passwd", "Egypt"):
            with self.assertRaises(ValueError):
                datetime_config.validate_timezone(invalid)

    def test_settings_default_save_and_load(self):
        self.assertEqual({"timezone": "UTC", "hour_format": 24},
                         datetime_config.load_settings())
        saved = datetime_config.save_settings(
            {"timezone": "Africa/Cairo", "hour_format": 12})
        with open(self.settings_file, encoding="utf-8") as source:
            self.assertEqual(saved, json.load(source))
        self.assertEqual(saved, datetime_config.load_settings())
        for invalid in ({"hour_format": 13}, {"hour_format": True},
                        {"timezone": "Nowhere"}):
            with self.assertRaises(ValueError):
                datetime_config.normalize_settings(invalid)
        with open(self.settings_file, "w") as broken:
            broken.write("{")
        self.assertEqual(datetime_config.DEFAULT_SETTINGS,
                         datetime_config.load_settings())

    def test_clock_is_set_after_the_build_date(self):
        build_date = calendar.timegm((2018, 3, 9, 12, 0, 0))
        self.assertFalse(datetime_config.clock_is_set(build_date))
        self.assertTrue(datetime_config.clock_is_set(
            calendar.timegm((2026, 10, 30, 13, 0, 0))))

    def test_set_clock_uses_the_time_zone_and_hardware_clock(self):
        shell = AsyncMock(return_value=(0, ""))
        with patch.object(datetime_config.utils, "exec_command", shell):
            self.assertTrue(asyncio.run(datetime_config.set_clock(
                "2026-10-30 14:30", "Africa/Cairo")))
        self.assertEqual(
            [(("date", "-s", 'TZ="Africa/Cairo" 2026-10-30 14:30'),),
             (("hwclock", "--systohc", "--utc"),)],
            [c.args and (c.args,) for c in shell.await_args_list])
        for invalid in ("2026-10-30", "2026-13-01 10:00", "2050-01-01 10:00",
                        "2018-01-01 10:00", "2026-10-30 14:30; reboot"):
            with self.assertRaises(ValueError):
                asyncio.run(datetime_config.set_clock(invalid, "UTC"))

    def test_status(self):
        ntp_config.save_settings({**ntp_config.DEFAULT_SETTINGS,
                                  "enabled": False})
        datetime_config.save_settings({"timezone": "Asia/Kolkata",
                                       "hour_format": 12})
        ntp_status = AsyncMock(return_value={"running": False,
                                             "synchronized": False})
        with patch.object(ntp_config, "service_status", ntp_status):
            status = asyncio.run(datetime_config.status())
        self.assertEqual({"timezone": "Asia/Kolkata", "hour_format": 12,
                          "clock_set": True, "ntp_enabled": False,
                          "synchronized": False}, status)


class WifiStatusTest(unittest.IsolatedAsyncioTestCase):
    LINK = ("Connected to 50:42:89:4c:fa:dc (on wlan0)\n"
            "\tSSID: Ahmed\n\tfreq: 2412\n\tsignal: -56 dBm\n")

    async def status(self, nw_mode, output, return_code=0):
        shell = AsyncMock(return_value=(return_code, output))
        with patch.object(network_functions, "_load_network_ui_config",
                          return_value={"nw_mode": nw_mode}), \
                patch.object(network_functions.utils, "exec_command", shell):
            return (await network_functions.get_wifi_status()).dict(), shell

    async def test_connected_with_signal(self):
        status, shell = await self.status(NetworkConfig.NW_LAN_WIFI, self.LINK)
        self.assertEqual({"enabled": True, "connected": True, "signal": -56},
                         status)
        shell.assert_awaited_once_with("iw", "dev", "wlan0", "link")

    async def test_not_connected(self):
        status, _ = await self.status(NetworkConfig.NW_WIFI_ONLY,
                                      "Not connected.\n")
        self.assertEqual({"enabled": True, "connected": False, "signal": None},
                         status)
        status, _ = await self.status(NetworkConfig.NW_WIFI_ONLY, "", 237)
        self.assertFalse(status["connected"])

    async def test_cable_only_does_not_ask_the_driver(self):
        status, shell = await self.status(NetworkConfig.NW_SINGLE_LAN, self.LINK)
        self.assertEqual({"enabled": False, "connected": False, "signal": None},
                         status)
        shell.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
