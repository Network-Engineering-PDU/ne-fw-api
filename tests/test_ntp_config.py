import asyncio
import json
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from ttne import ntp_config


class NtpConfigTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.settings_file = os.path.join(self.directory.name, "settings.json")
        self.chrony_file = os.path.join(self.directory.name, "chrony.conf")
        self.disabled_file = os.path.join(self.directory.name, "disabled")
        self.paths = patch.multiple(
            ntp_config,
            NTP_SETTINGS_FILE=self.settings_file,
            CHRONY_CONFIG_FILE=self.chrony_file,
            NTP_DISABLED_FILE=self.disabled_file,
        )
        self.paths.start()

    def tearDown(self):
        self.paths.stop()
        self.directory.cleanup()

    def test_validates_server_and_offset(self):
        self.assertEqual("192.0.2.1", ntp_config.validate_server("192.0.2.1"))
        self.assertEqual("time.example.com",
                         ntp_config.validate_server("time.example.com"))
        for invalid in ("", "bad server", "server;reboot", "-bad.example",
                        "a" * 128):
            with self.assertRaises(ValueError):
                ntp_config.validate_server(invalid)
        with self.assertRaises(ValueError):
            ntp_config.normalize_settings({
                "enabled": True, "time_offset": 13, "server": "pool.ntp.org"
            })

    def test_saves_atomic_settings_chrony_config_and_disabled_marker(self):
        settings = ntp_config.save_settings({
            "enabled": False,
            "time_offset": 2,
            "server": "time.example.com",
        })
        self.assertFalse(settings["enabled"])
        with open(self.settings_file, encoding="utf-8") as source:
            self.assertEqual(settings, json.load(source))
        with open(self.chrony_file, encoding="utf-8") as source:
            rendered = source.read()
        self.assertIn("server time.example.com iburst\n", rendered)
        self.assertNotIn("UTC+02", rendered)
        self.assertTrue(os.path.isfile(self.disabled_file))

        ntp_config.save_settings({**settings, "enabled": True})
        self.assertFalse(os.path.exists(self.disabled_file))

    def test_apply_uses_argv_and_restores_service_state(self):
        shell = AsyncMock(return_value=(0, "ok"))
        with patch.object(ntp_config.utils, "exec_command", shell):
            self.assertTrue(asyncio.run(ntp_config.apply_settings({
                "enabled": True,
                "time_offset": 0,
                "server": "pool.ntp.org",
            })))
            shell.assert_awaited_once_with(ntp_config.CHRONY_INIT, "restart")

            shell.reset_mock()
            self.assertTrue(asyncio.run(ntp_config.apply_settings({
                "enabled": False,
                "time_offset": 0,
                "server": "pool.ntp.org",
            })))
            shell.assert_awaited_once_with(ntp_config.CHRONY_INIT, "stop")

    def test_status_reports_chrony_synchronization(self):
        ntp_config.save_settings(dict(ntp_config.DEFAULT_SETTINGS))
        output = "Reference ID : C0000201\nLeap status     : Normal\n"
        shell = AsyncMock(return_value=(0, output))
        with patch.object(ntp_config.utils, "exec_command", shell):
            status = asyncio.run(ntp_config.service_status())
        self.assertEqual({"running": True, "synchronized": True}, status)
        shell.assert_awaited_once_with("chronyc", "-n", "tracking")


if __name__ == "__main__":
    unittest.main()
