import unittest
from unittest.mock import AsyncMock, patch

from ttne.app.network import functions
from ttne.network_config import NetworkConfig
from ttne.network_type import NetworkType


class NetworkFunctionsTest(unittest.IsolatedAsyncioTestCase):

    async def test_static_lan_wifi_reports_live_dhcp_wifi_address(self):
        saved_config = {
            "type": NetworkType.ETH_STATIC,
            "dhcp": False,
            "nw_mode": NetworkConfig.NW_LAN_WIFI,
            "ip": "192.168.1.100",
            "subnet_mask": "255.255.255.0",
            "gateway_ip": "192.168.1.1",
            "dns": "8.8.8.8",
            "ssid": "Ahmed",
            "eth_interface": "eth0",
            "lan1_ip": "192.168.1.100",
            "lan2_ip": "192.168.1.200",
            "wifi_ip": "",
        }

        with patch.object(
            functions,
            "_load_network_ui_config",
            return_value=saved_config,
        ), patch.object(
            functions,
            "_current_ip",
            new=AsyncMock(return_value="192.168.1.2"),
        ) as current_ip, patch.object(
            functions,
            "get_iface_mac",
            new=AsyncMock(return_value="00:11:22:33:44:55"),
        ):
            config = await functions.get_network_config()

        self.assertEqual(config.wifi_ip, "192.168.1.2")
        current_ip.assert_awaited_once()
        self.assertEqual(current_ip.await_args.args[1], "wlan0")


if __name__ == "__main__":
    unittest.main()
