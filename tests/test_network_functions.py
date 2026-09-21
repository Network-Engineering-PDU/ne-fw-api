import unittest
from unittest.mock import AsyncMock, patch

from ttne.app.network import functions
from ttne.network_config import NetworkConfig
from ttne.network_type import NetworkType


class NetworkFunctionsTest(unittest.IsolatedAsyncioTestCase):

    def _static_lan_wifi_config(self, **overrides):
        data = {
            "type": NetworkType.ETH_STATIC,
            "dhcp": False,
            "nw_mode": NetworkConfig.NW_LAN_WIFI,
            "params": {
                "ip": "192.168.1.100",
                "subnet_mask": "255.255.255.0",
                "gateway_ip": "192.168.1.1",
                "dns": "8.8.8.8",
                "ssid": "Ahmed",
                "password": "correct-password",
            },
            "lan1_ip": "192.168.1.100",
            "wifi_ip": "10.20.30.40",
            "wifi_subnet_mask": "255.255.255.0",
            "wifi_gateway": "10.20.30.1",
            "wifi_dns": "1.1.1.1",
        }
        data.update(overrides)
        return functions.models.BaseNetworkConfig(**data)

    def test_static_lan_wifi_accepts_independent_interface_settings(self):
        functions.validate_network_config(self._static_lan_wifi_config())

    def test_static_lan_wifi_requires_wifi_ip_and_mask(self):
        for field in ("wifi_ip", "wifi_subnet_mask"):
            with self.subTest(field=field), self.assertRaises(ValueError):
                functions.validate_network_config(
                    self._static_lan_wifi_config(**{field: ""})
                )

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
            "wifi_subnet_mask": "255.255.255.0",
            "wifi_gateway": "192.168.1.1",
            "wifi_dns": "1.1.1.1",
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
        self.assertEqual(config.wifi_subnet_mask, "255.255.255.0")
        self.assertEqual(config.wifi_gateway, "192.168.1.1")
        self.assertEqual(config.wifi_dns, "1.1.1.1")
        current_ip.assert_awaited_once()
        self.assertEqual(current_ip.await_args.args[1], "wlan0")

    async def test_lan_wifi_uses_dedicated_wifi_defaults_when_disconnected(self):
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
            "wifi_ip": "",
        }

        with patch.object(
            functions,
            "_load_network_ui_config",
            return_value=saved_config,
        ), patch.object(
            functions,
            "_current_ip",
            new=AsyncMock(return_value=""),
        ), patch.object(
            functions,
            "get_iface_mac",
            new=AsyncMock(return_value="00:11:22:33:44:55"),
        ):
            config = await functions.get_network_config()

        self.assertEqual(config.wifi_ip, "192.168.1.150")
        self.assertEqual(config.wifi_subnet_mask, "255.255.255.0")
        self.assertEqual(config.wifi_gateway, "192.168.1.1")
        self.assertEqual(config.wifi_dns, "8.8.8.8")


if __name__ == "__main__":
    unittest.main()
