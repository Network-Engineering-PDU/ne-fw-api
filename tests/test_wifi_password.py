import os
import stat
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import Response

from ttne import network_config
from ttne.app.network import functions, models, routers
from ttne.network_config import NetworkConfig
from ttne.network_type import NetworkType


class WifiPasswordTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.secret = os.path.join(self.directory.name, "wifi_secret.json")
        self.paths = patch.object(network_config, "WIFI_SECRET_FILE", self.secret)
        self.paths.start()

    def tearDown(self):
        self.paths.stop()
        self.directory.cleanup()

    def test_kept_password_is_root_only_and_per_ssid(self):
        network_config.remember_wifi_psk("Ahmed", "secret-1")
        self.assertEqual(0o600, stat.S_IMODE(os.stat(self.secret).st_mode))
        self.assertEqual("secret-1", network_config.remembered_wifi_psk("Ahmed"))
        self.assertEqual("", network_config.remembered_wifi_psk("Other"))
        network_config.remember_wifi_psk("Ahmed", "")
        self.assertEqual("secret-1", network_config.remembered_wifi_psk("Ahmed"))

    async def test_saved_password_falls_back_to_the_kept_one(self):
        network_config.remember_wifi_psk("Ahmed", "secret-1")
        # The WiFi profile was deleted by a mode without WiFi.
        shell = AsyncMock(return_value=(10, "Error: no such connection"))
        with patch.object(network_config.utils, "exec_command", shell):
            self.assertEqual("secret-1",
                             await NetworkConfig().get_saved_wifi_psk("Ahmed"))
            self.assertEqual("", await NetworkConfig().get_saved_wifi_psk("Other"))

    def _lan_wifi(self, password):
        return models.BaseNetworkConfig(
            type=NetworkType.ETH_STATIC, dhcp=False, nw_mode=NetworkConfig.NW_LAN_WIFI,
            params=models.NetworkConfigParams(
                ip="192.168.1.100", subnet_mask="255.255.255.0",
                gateway_ip="192.168.1.1", dns="8.8.8.8", ssid="Ahmed",
                password=password),
            lan1_ip="192.168.1.100", wifi_ip="192.168.1.150",
            wifi_subnet_mask="255.255.255.0", wifi_gateway="192.168.1.1",
            wifi_dns="8.8.8.8")

    async def test_wifi_without_any_password_is_refused_before_applying(self):
        shell = AsyncMock(return_value=(10, ""))
        with patch.object(network_config.utils, "exec_command", shell), \
                patch.object(functions, "save_network_ui_config") as save, \
                patch.object(routers.utils, "schedule_in") as schedule:
            response = Response()
            result = await routers.put_interfaces(self._lan_wifi(""), response)
            self.assertEqual(400, response.status_code)
            self.assertEqual("wifi_password", result["code"])
            save.assert_not_called()
            schedule.assert_not_called()

            # A kept password, or a typed one, is applied.
            network_config.remember_wifi_psk("Ahmed", "secret-1")
            response = Response()
            await routers.put_interfaces(self._lan_wifi(""), response)
            self.assertEqual(202, response.status_code)
            response = Response()
            await routers.put_interfaces(self._lan_wifi("typed"), response)
            self.assertEqual(202, response.status_code)
            self.assertEqual(2, schedule.call_count)
            for call in schedule.call_args_list:
                call.args[1].close()    # the scheduled coroutines


if __name__ == "__main__":
    unittest.main()
