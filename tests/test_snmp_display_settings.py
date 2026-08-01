import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch


sys.modules.setdefault("ttgateway", MagicMock())
sys.modules.setdefault("ttgateway.commands", MagicMock())
sys.modules.setdefault("ttgateway.config", MagicMock())

from fastapi import Response
from pydantic import ValidationError

from ttne.app.network import models, routers


class SnmpDisplaySettingsTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.old_basic = routers.snmp_config
        self.old_detailed = routers.snmp_detailed_settings
        routers.snmp_config = models.SnmpConfig(
            beep=True,
            relay=False,
            trap_alarm=True,
            email_alarm=False,
            refresh_period=60,
            life_time=240,
            datetime="2026-08-01 00:00:00",
            modbus_address=1,
        )
        routers.snmp_detailed_settings = models.SnmpDetailedConfig(
            port=161,
            trap=models.SnmpTrapConfig(alarm=True),
            snmp_v1_v2c=models.SnmpV1Config(
                read_community="public",
                write_community="protected",
            ),
            set_enabled=True,
        )

    def tearDown(self):
        routers.snmp_config = self.old_basic
        routers.snmp_detailed_settings = self.old_detailed

    async def test_get_combines_service_basic_and_detailed_settings(self):
        routers.snmp_detailed_settings.trap.manager_1_ip = "trap.example.test"
        with patch.object(
                routers.functions, "read_services",
                AsyncMock(return_value=(1, 1, 0))):
            result = await routers.get_snmp_display_settings()

        self.assertTrue(result.enabled)
        self.assertTrue(result.set_enabled)
        self.assertTrue(result.traps_enabled)
        self.assertEqual("public", result.community)
        self.assertEqual("trap.example.test", result.manager_1)

    async def test_put_preserves_private_community_and_applies_runtime(self):
        requested = models.SnmpDisplayConfig(
            enabled=True,
            set_enabled=False,
            community="monitor",
            traps_enabled=True,
            manager_1="traps.example.test",
            manager_2="192.0.2.10",
        )
        response = Response()
        with patch.object(routers, "_save_snmp_settings") as save, patch(
                "ttne.app.settings.functions.apply_snmp_configuration",
                AsyncMock(return_value=True)) as apply, patch.object(
                routers.functions, "read_services",
                AsyncMock(return_value=(1, 1, 0))):
            result = await routers.put_snmp_display_settings(
                requested, response
            )

        save.assert_called_once_with()
        apply.assert_awaited_once_with(True)
        self.assertEqual(200, response.status_code)
        self.assertFalse(routers.snmp_detailed_settings.set_enabled)
        self.assertEqual(
            "protected",
            routers.snmp_detailed_settings.snmp_v1_v2c.write_community,
        )
        self.assertEqual("monitor", result.community)
        self.assertEqual("traps.example.test", result.manager_1)
        self.assertEqual("192.0.2.10", result.manager_2)

    def test_rejects_unsafe_community_and_trap_target(self):
        with self.assertRaises(ValidationError):
            models.SnmpDisplayConfig(
                enabled=True,
                set_enabled=True,
                community="bad community",
                traps_enabled=True,
            )
        with self.assertRaises(ValidationError):
            models.SnmpDisplayConfig(
                enabled=True,
                set_enabled=True,
                community="public",
                traps_enabled=True,
                manager_1="bad target!",
            )
        with self.assertRaises(ValidationError):
            models.SnmpDisplayConfig(
                enabled=True,
                set_enabled=True,
                community="public",
                traps_enabled=True,
                manager_1="999.999.999.999",
            )


if __name__ == "__main__":
    unittest.main()
