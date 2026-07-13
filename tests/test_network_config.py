import unittest
from unittest.mock import AsyncMock, patch

from ttne.network_config import NetworkConfig


class NetworkConfigTest(unittest.IsolatedAsyncioTestCase):

    async def test_active_interface_detection_uses_exact_state(self):
        config = NetworkConfig()

        with patch(
            "ttne.network_config.utils.shell",
            new=AsyncMock(side_effect=[
                (0, "30 (disconnected)\n"),
                (0, "100 (connected)\n"),
            ]),
        ):
            self.assertEqual(await config._get_active_eth_if(), "eth1")

    async def test_dual_lan_repair_skips_active_connection(self):
        config = NetworkConfig()
        config._is_dual_lan_configured = AsyncMock(return_value=True)
        config._get_linked_eth_interfaces = AsyncMock(return_value=["eth1"])
        config._get_active_connections = AsyncMock(return_value={
            config.LAN1_CONN: "eth1",
        })

        with patch("ttne.network_config.os.path.exists", return_value=False), patch(
            "ttne.network_config.utils.shell", new=AsyncMock()
        ) as shell:
            await config.repair_ethernet_activation()

        shell.assert_not_awaited()

    async def test_dual_lan_repair_activates_missing_connection(self):
        config = NetworkConfig()
        config._is_dual_lan_configured = AsyncMock(return_value=True)
        config._get_linked_eth_interfaces = AsyncMock(return_value=["eth1"])
        config._get_active_connections = AsyncMock(return_value={})

        with patch("ttne.network_config.os.path.exists", return_value=False), patch(
            "ttne.network_config.utils.shell", new=AsyncMock(return_value=(0, ""))
        ) as shell:
            await config.repair_ethernet_activation()

        shell.assert_awaited_once_with(
            "nmcli -w 10 con up 'ble-eth-lan1-conn' ifname 'eth1' || true"
        )

    async def test_dual_lan_repair_deactivates_unlinked_active_connection(self):
        config = NetworkConfig()
        config._is_dual_lan_configured = AsyncMock(return_value=True)
        config._get_linked_eth_interfaces = AsyncMock(return_value=["eth1"])
        config._get_active_connections = AsyncMock(return_value={
            config.LAN1_CONN: "eth1",
            config.LAN2_CONN: "eth0",
        })

        with patch("ttne.network_config.os.path.exists", return_value=False), patch(
            "ttne.network_config.utils.shell", new=AsyncMock(return_value=(0, ""))
        ) as shell:
            await config.repair_ethernet_activation()

        shell.assert_awaited_once_with(
            "nmcli con down 'ble-eth-lan2-conn' || true"
        )


if __name__ == "__main__":
    unittest.main()
