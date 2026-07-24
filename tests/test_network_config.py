import unittest
from unittest.mock import AsyncMock, call, patch

from ttne.network_config import NetworkConfig
from ttne.network_type import NetworkType


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

    async def test_portable_profile_is_not_rewritten_on_every_repair(self):
        config = NetworkConfig()

        with patch(
            "ttne.network_config.utils.shell",
            new=AsyncMock(return_value=(0, "\n")),
        ) as shell:
            await config._ensure_eth_profile_portable()

        shell.assert_awaited_once_with(
            "nmcli -g connection.interface-name con show ble-eth-conn"
        )

    async def test_dual_lan_repair_skips_active_connection(self):
        config = NetworkConfig()
        config._is_dual_lan_configured = AsyncMock(return_value=True)
        config._get_linked_eth_interfaces = AsyncMock(return_value=["eth1"])
        config._get_active_connections = AsyncMock(return_value={
            config.LAN1_CONN: "eth1",
        })
        config._dual_lan_policy_initialized = True
        config._dual_lan_policy_is_current = AsyncMock(return_value=True)

        with patch("ttne.network_config.os.path.exists", return_value=False), patch(
            "ttne.network_config.utils.shell", new=AsyncMock()
        ) as shell:
            await config.repair_ethernet_activation()

        shell.assert_not_awaited()

    async def test_dual_lan_repair_restores_missing_policy(self):
        config = NetworkConfig()
        config._is_dual_lan_configured = AsyncMock(return_value=True)
        config._get_linked_eth_interfaces = AsyncMock(return_value=["eth1"])
        active_connections = {config.LAN1_CONN: "eth1"}
        config._get_active_connections = AsyncMock(
            return_value=active_connections
        )
        config._dual_lan_policy_initialized = True
        config._dual_lan_policy_is_current = AsyncMock(return_value=False)
        config._apply_dual_lan_policy_routing = AsyncMock(return_value=True)

        with patch(
            "ttne.network_config.os.path.exists",
            return_value=False,
        ):
            await config.repair_ethernet_activation()

        config._apply_dual_lan_policy_routing.assert_awaited_once_with(
            active_connections
        )

    async def test_dual_lan_repair_activates_missing_connection(self):
        config = NetworkConfig()
        config._is_dual_lan_configured = AsyncMock(return_value=True)
        config._get_linked_eth_interfaces = AsyncMock(return_value=["eth1"])
        config._get_active_connections = AsyncMock(return_value={})
        config._apply_dual_lan_policy_routing = AsyncMock()

        with patch("ttne.network_config.os.path.exists", return_value=False), patch(
            "ttne.network_config.utils.shell", new=AsyncMock(return_value=(0, ""))
        ) as shell:
            await config.repair_ethernet_activation()

        shell.assert_awaited_once_with(
            "nmcli -w 10 con up 'ble-eth-lan1-conn' ifname 'eth1' || true"
        )
        config._apply_dual_lan_policy_routing.assert_awaited_once_with({})

    async def test_dual_lan_repair_deactivates_unlinked_active_connection(self):
        config = NetworkConfig()
        config._is_dual_lan_configured = AsyncMock(return_value=True)
        config._get_linked_eth_interfaces = AsyncMock(return_value=["eth1"])
        config._get_active_connections = AsyncMock(side_effect=[
            {
                config.LAN1_CONN: "eth1",
                config.LAN2_CONN: "eth0",
            },
            {
                config.LAN1_CONN: "eth1",
            },
        ])
        config._apply_dual_lan_policy_routing = AsyncMock()

        with patch("ttne.network_config.os.path.exists", return_value=False), patch(
            "ttne.network_config.utils.shell", new=AsyncMock(return_value=(0, ""))
        ) as shell:
            await config.repair_ethernet_activation()

        shell.assert_awaited_once_with(
            "nmcli con down 'ble-eth-lan2-conn' || true"
        )
        config._apply_dual_lan_policy_routing.assert_awaited_once_with({
            config.LAN1_CONN: "eth1",
        })

    async def test_dual_lan_policy_routes_each_source_to_its_interface(self):
        config = NetworkConfig()
        config._set_dual_lan_arp_settings = AsyncMock(return_value=True)
        config._read_ip_from_if = AsyncMock(side_effect=[
            ("192.168.1.100", "255.255.255.0", "192.168.1.1"),
            ("192.168.1.200", "255.255.255.0", None),
        ])
        active_connections = {
            config.LAN1_CONN: config.LAN1_IFACE,
            config.LAN2_CONN: config.LAN2_IFACE,
        }

        with patch(
            "ttne.network_config.utils.exec_command",
            new=AsyncMock(return_value=(0, "")),
        ) as exec_command:
            await config._apply_dual_lan_policy_routing(active_connections)

        config._set_dual_lan_arp_settings.assert_awaited_once_with(True)
        self.assertEqual(exec_command.await_args_list, [
            call("ip", "-4", "rule", "del", "priority", "1001"),
            call("ip", "-4", "route", "flush", "table", "101"),
            call(
                "ip", "-4", "route", "add", "table", "101",
                "192.168.1.0/24", "dev", "eth1", "src", "192.168.1.100",
            ),
            call(
                "ip", "-4", "rule", "add", "priority", "1001",
                "from", "192.168.1.100/32", "table", "101",
            ),
            call("ip", "-4", "rule", "del", "priority", "1002"),
            call("ip", "-4", "route", "flush", "table", "102"),
            call(
                "ip", "-4", "route", "add", "table", "102",
                "192.168.1.0/24", "dev", "eth0", "src", "192.168.1.200",
            ),
            call(
                "ip", "-4", "rule", "add", "priority", "1002",
                "from", "192.168.1.200/32", "table", "102",
            ),
        ])
        self.assertTrue(config._dual_lan_policy_initialized)

    async def test_dual_lan_policy_retries_after_command_failure(self):
        config = NetworkConfig()
        config._set_dual_lan_arp_settings = AsyncMock(return_value=True)
        config._read_ip_from_if = AsyncMock(return_value=(
            "192.168.1.200",
            "255.255.255.0",
            None,
        ))

        async def fail_lan2_route(*args):
            if (
                args[:7]
                == ("ip", "-4", "route", "add", "table", "102", "192.168.1.0/24")
            ):
                return 2, "route failed"
            return 0, ""

        with patch(
            "ttne.network_config.utils.exec_command",
            new=AsyncMock(side_effect=fail_lan2_route),
        ):
            success = await config._apply_dual_lan_policy_routing({
                config.LAN2_CONN: config.LAN2_IFACE,
            })

        self.assertFalse(success)
        self.assertFalse(config._dual_lan_policy_initialized)
        self.assertEqual(
            config._set_dual_lan_arp_settings.await_args_list,
            [call(True), call(False)],
        )

    async def test_dual_lan_policy_removes_rule_for_disconnected_port(self):
        config = NetworkConfig()
        config._set_dual_lan_arp_settings = AsyncMock(return_value=True)
        config._read_ip_from_if = AsyncMock(return_value=(
            "192.168.1.100",
            "255.255.255.0",
            "192.168.1.1",
        ))

        with patch(
            "ttne.network_config.utils.exec_command",
            new=AsyncMock(return_value=(0, "")),
        ) as exec_command:
            success = await config._apply_dual_lan_policy_routing({
                config.LAN1_CONN: config.LAN1_IFACE,
            })

        self.assertTrue(success)
        self.assertIn(
            call("ip", "-4", "rule", "del", "priority", "1002"),
            exec_command.await_args_list,
        )
        self.assertIn(
            call("ip", "-4", "route", "flush", "table", "102"),
            exec_command.await_args_list,
        )

    async def test_clear_dual_policy_is_noop_when_not_installed(self):
        config = NetworkConfig()
        config._set_dual_lan_arp_settings = AsyncMock()
        normal_rules = (
            "0: from all lookup local\n"
            "32766: from all lookup main\n"
            "32767: from all lookup default\n"
        )

        with patch(
            "ttne.network_config.utils.exec_command",
            new=AsyncMock(return_value=(0, normal_rules)),
        ) as exec_command:
            await config._clear_dual_lan_policy_routing()

        exec_command.assert_awaited_once_with("ip", "-4", "rule", "show")
        config._set_dual_lan_arp_settings.assert_not_awaited()
        self.assertFalse(config._dual_lan_policy_initialized)

    async def test_single_lan_repair_never_applies_dual_policy(self):
        config = NetworkConfig()
        config._is_dual_lan_configured = AsyncMock(return_value=False)
        config._ensure_eth_profile_portable = AsyncMock()
        config._get_linked_eth_interfaces = AsyncMock(
            return_value=[config.LAN1_IFACE]
        )
        config._get_active_connections = AsyncMock(return_value={
            config.ETH_CONN: config.LAN1_IFACE,
        })
        config._apply_dual_lan_policy_routing = AsyncMock()

        with patch("ttne.network_config.os.path.exists", return_value=False), patch(
            "ttne.network_config.utils.shell",
            new=AsyncMock(return_value=(0, "")),
        ):
            await config.repair_ethernet_activation()

        config._apply_dual_lan_policy_routing.assert_not_awaited()

    async def test_wifi_only_repair_does_not_create_ethernet_profile(self):
        config = NetworkConfig()
        config._load_saved_network_config = lambda: {
            "nw_mode": config.NW_WIFI_ONLY,
        }
        config._is_dual_lan_configured = AsyncMock(return_value=False)
        config._connection_exists = AsyncMock(return_value=True)
        config.save = AsyncMock()
        config._restore_missing_single_ethernet_profile = AsyncMock()

        with patch("ttne.network_config.os.path.exists", return_value=False), patch(
            "ttne.network_config.utils.shell",
            new=AsyncMock(return_value=(10, "missing")),
        ):
            await config.repair_ethernet_activation()

        config.save.assert_not_awaited()
        config._restore_missing_single_ethernet_profile.assert_not_awaited()
        config._is_dual_lan_configured.assert_not_awaited()

    async def test_saved_single_lan_ignores_stale_dual_lan_profiles(self):
        config = NetworkConfig()
        config._load_saved_network_config = lambda: {
            "nw_mode": config.NW_SINGLE_LAN,
        }
        config._is_dual_lan_configured = AsyncMock(return_value=True)
        config._ensure_eth_profile_portable = AsyncMock()
        config._get_linked_eth_interfaces = AsyncMock(
            return_value=[config.LAN1_IFACE]
        )
        config._get_active_connections = AsyncMock(return_value={
            config.ETH_CONN: config.LAN1_IFACE,
        })
        config._apply_dual_lan_policy_routing = AsyncMock()

        with patch("ttne.network_config.os.path.exists", return_value=False), patch(
            "ttne.network_config.utils.shell",
            new=AsyncMock(return_value=(0, "")),
        ):
            await config.repair_ethernet_activation()

        config._is_dual_lan_configured.assert_not_awaited()
        config._apply_dual_lan_policy_routing.assert_not_awaited()

    async def test_saved_single_lan_profile_is_restored_without_wifi_changes(self):
        config = NetworkConfig()
        saved_config = {
            "nw_mode": config.NW_SINGLE_LAN,
            "dhcp": False,
            "ip": "10.20.30.40",
            "subnet_mask": "255.255.255.0",
            "gateway_ip": "",
            "dns": "",
            "eth_interface": config.LAN2_IFACE,
        }
        config._load_saved_network_config = lambda: saved_config
        config._is_dual_lan_configured = AsyncMock(return_value=False)
        config._connection_exists = AsyncMock(return_value=False)
        config._restore_missing_single_ethernet_profile = AsyncMock()

        with patch("ttne.network_config.os.path.exists", return_value=False), patch(
            "ttne.network_config.utils.shell",
            new=AsyncMock(return_value=(10, "missing")),
        ):
            await config.repair_ethernet_activation()

        config._restore_missing_single_ethernet_profile.assert_awaited_once_with(
            saved_config
        )

    async def test_saved_dual_lan_restores_both_missing_profiles(self):
        config = NetworkConfig()
        config._load_saved_network_config = lambda: {
            "nw_mode": config.NW_DUAL_LAN,
            "dhcp": False,
            "lan1_ip": "192.168.1.100",
            "lan2_ip": "192.168.1.200",
            "subnet_mask": "255.255.255.0",
        }
        config._is_dual_lan_configured = AsyncMock(side_effect=[False, True])
        config._restore_missing_dual_lan_profiles = AsyncMock(return_value=True)
        config._get_linked_eth_interfaces = AsyncMock(return_value=[])
        config._get_active_connections = AsyncMock(return_value={})
        config._apply_dual_lan_policy_routing = AsyncMock(return_value=True)

        with patch("ttne.network_config.os.path.exists", return_value=False):
            await config.repair_ethernet_activation()

        config._restore_missing_dual_lan_profiles.assert_awaited_once_with(
            (False, False)
        )

    async def test_single_lan_activates_on_either_connected_port(self):
        for target_iface in (NetworkConfig.LAN1_IFACE, NetworkConfig.LAN2_IFACE):
            with self.subTest(target_iface=target_iface):
                config = NetworkConfig()
                config._is_dual_lan_configured = AsyncMock(return_value=False)
                config._ensure_eth_profile_portable = AsyncMock()
                config._get_linked_eth_interfaces = AsyncMock(
                    return_value=[target_iface]
                )
                config._get_active_connections = AsyncMock(return_value={})

                with patch(
                    "ttne.network_config.os.path.exists",
                    return_value=False,
                ), patch(
                    "ttne.network_config.utils.shell",
                    new=AsyncMock(return_value=(0, "")),
                ) as shell:
                    await config.repair_ethernet_activation()

                self.assertEqual(shell.await_args_list, [
                    call(f"nmcli -t con show {config.ETH_CONN}"),
                    call(f"nmcli con down {config.ETH_CONN} || true"),
                    call(
                        f"nmcli -w 10 con up {config.ETH_CONN} "
                        f"ifname '{target_iface}' || "
                        f"nmcli -w 10 con up {config.ETH_CONN} || true"
                    ),
                ])

    async def test_single_lan_ignores_unrelated_active_ethernet_profile(self):
        config = NetworkConfig()
        config._is_dual_lan_configured = AsyncMock(return_value=False)
        config._ensure_eth_profile_portable = AsyncMock()
        config._get_linked_eth_interfaces = AsyncMock(
            return_value=[config.LAN2_IFACE]
        )
        config._get_active_connections = AsyncMock(return_value={
            "Wired connection 1": config.LAN2_IFACE,
        })

        with patch("ttne.network_config.os.path.exists", return_value=False), patch(
            "ttne.network_config.utils.shell",
            new=AsyncMock(return_value=(0, "")),
        ) as shell:
            await config.repair_ethernet_activation()

        self.assertIn(
            call(
                f"nmcli -w 10 con up {config.ETH_CONN} "
                f"ifname '{config.LAN2_IFACE}' || "
                f"nmcli -w 10 con up {config.ETH_CONN} || true"
            ),
            shell.await_args_list,
        )

    async def test_single_lan_deactivates_profile_when_both_ports_unplugged(self):
        config = NetworkConfig()
        config._is_dual_lan_configured = AsyncMock(return_value=False)
        config._ensure_eth_profile_portable = AsyncMock()
        config._get_linked_eth_interfaces = AsyncMock(return_value=[])
        config._get_active_connections = AsyncMock(return_value={
            config.ETH_CONN: config.LAN1_IFACE,
        })

        with patch("ttne.network_config.os.path.exists", return_value=False), patch(
            "ttne.network_config.utils.shell",
            new=AsyncMock(return_value=(0, "")),
        ) as shell:
            await config.repair_ethernet_activation()

        shell.assert_any_await(
            f"nmcli con down {config.ETH_CONN} || true"
        )

    async def test_single_lan_and_wifi_never_apply_dual_policy(self):
        for setter_name in ("set_ethernet", "set_wifi"):
            with self.subTest(setter=setter_name):
                config = NetworkConfig()
                config._clear_dual_lan_policy_routing = AsyncMock()
                config._delete_single_eth_connection = AsyncMock()
                config._delete_dual_lan_connections = AsyncMock()
                config._delete_wifi_connection = AsyncMock()
                config._add_ethernet_connection = AsyncMock()
                config._activate_ethernet_connection = AsyncMock()
                config._add_wifi_connection = AsyncMock()
                config._activate_wifi_connection = AsyncMock()
                config._apply_dual_lan_policy_routing = AsyncMock()

                await getattr(config, setter_name)()

                config._clear_dual_lan_policy_routing.assert_awaited_once_with()
                config._apply_dual_lan_policy_routing.assert_not_awaited()

    async def test_lan_wifi_keeps_wifi_and_portable_single_lan_behavior(self):
        config = NetworkConfig()
        config.eth_interface = config.LAN1_IFACE
        config._clear_dual_lan_policy_routing = AsyncMock()
        config._delete_single_eth_connection = AsyncMock()
        config._delete_dual_lan_connections = AsyncMock()
        config._delete_wifi_connection = AsyncMock()
        config._add_ethernet_connection = AsyncMock()
        config._add_wifi_connection = AsyncMock()
        config._get_linked_eth_interfaces = AsyncMock(
            return_value=[config.LAN2_IFACE]
        )
        config._activate_ethernet_connection = AsyncMock()
        config._activate_wifi_connection = AsyncMock()
        config._apply_dual_lan_policy_routing = AsyncMock()

        await config.set_lan_wifi()

        config._clear_dual_lan_policy_routing.assert_awaited_once_with()
        config._add_ethernet_connection.assert_awaited_once_with()
        config._add_wifi_connection.assert_awaited_once_with(
            route_metric=600,
            force_dhcp=True,
        )
        self.assertEqual(config.eth_interface, config.LAN2_IFACE)
        config._activate_ethernet_connection.assert_awaited_once_with()
        config._activate_wifi_connection.assert_awaited_once_with()
        config._apply_dual_lan_policy_routing.assert_not_awaited()

    async def test_incomplete_dual_lan_profile_is_restored(self):
        config = NetworkConfig()
        config._get_dual_lan_profile_state = AsyncMock(side_effect=[
            (True, False),
            (True, True),
        ])
        config._restore_missing_dual_lan_profiles = AsyncMock(return_value=True)

        self.assertTrue(await config._is_dual_lan_configured())
        config._restore_missing_dual_lan_profiles.assert_awaited_once_with(
            (True, False)
        )

    async def test_wifi_credentials_are_passed_as_literal_arguments(self):
        config = NetworkConfig()
        config.type = NetworkType.WIFI_DHCP
        config.ssid = "Client's $(ssid)"
        config.psk = "p@ss'; $(reboot)"

        with patch(
            "ttne.network_config.utils.exec_command",
            new=AsyncMock(return_value=(0, "")),
        ) as exec_command:
            await config._add_wifi_connection()

        args = exec_command.await_args.args
        self.assertIn(config.ssid, args)
        self.assertIn(config.psk, args)
        self.assertNotIn("sh", args)

    async def test_static_single_lan_allows_empty_gateway_and_dns(self):
        config = NetworkConfig()
        config.type = NetworkType.ETH_STATIC
        config.ip = "192.168.50.10"
        config.mask = "255.255.255.0"
        config.gateway = ""
        config.dns1 = ""
        config.dns2 = ""

        with patch(
            "ttne.network_config.utils.exec_command",
            new=AsyncMock(return_value=(0, "")),
        ) as exec_command:
            await config._add_ethernet_connection()

        args = exec_command.await_args.args
        self.assertNotIn("gw4", args)
        self.assertNotIn("ipv4.dns", args)

    async def test_dual_lan_removes_stale_wifi_profile(self):
        config = NetworkConfig()
        config.nw_mode = config.NW_DUAL_LAN
        config._disable_auto_wired_connections = AsyncMock()
        config._delete_wifi_connection = AsyncMock()
        config._add_dual_lan_connection = AsyncMock(return_value=True)
        config._get_linked_eth_interfaces = AsyncMock(return_value=[])
        config._get_active_connections = AsyncMock(return_value={})
        config._apply_dual_lan_policy_routing = AsyncMock(return_value=True)

        with patch(
            "ttne.network_config.utils.shell",
            new=AsyncMock(return_value=(0, "")),
        ):
            await config.set_dual_lan()

        config._delete_wifi_connection.assert_awaited_once_with()


if __name__ == "__main__":
    unittest.main()
