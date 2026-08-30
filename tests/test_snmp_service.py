import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch


# The Yocto image supplies ttgateway. Boot restoration itself does not use it,
# so keep this focused host-side unit test independent of that target package.
sys.modules.setdefault("ttgateway", MagicMock())
sys.modules.setdefault("ttgateway.commands", MagicMock())
sys.modules.setdefault("ttgateway.config", MagicMock())

from ttne.app.settings import functions


class SnmpServiceTest(unittest.IsolatedAsyncioTestCase):

    async def test_start_repairs_enabled_but_stopped_daemon(self):
        with patch.object(
                functions.nw_functions, "read_services",
                AsyncMock(return_value=(0, 1, 0))), patch.object(
                functions, "_launch_snmp",
                AsyncMock(return_value=True)) as launch:
            started = await functions.start_snmp()

        self.assertTrue(started)
        launch.assert_awaited_once_with()

    async def test_restore_starts_daemon_when_persistently_enabled(self):
        with patch.object(
                functions.nw_functions, "read_services",
                AsyncMock(return_value=(0, 1, 0))), patch.object(
                functions.os, "makedirs"), patch.object(
                functions, "write_snmp_config") as write_config, patch.object(
                functions, "write_snmp_v3_user") as write_v3, patch.object(
                functions.utils, "shell",
                AsyncMock(side_effect=[(0, ""), (0, "")])) as shell, \
                patch.object(functions.utils, "exec_command",
                             AsyncMock(return_value=(0, ""))) as execute:
            restored = await functions.restore_snmp()

        self.assertTrue(restored)
        write_config.assert_called_once_with()
        write_v3.assert_called_once_with()
        self.assertEqual([
            unittest.mock.call("/usr/bin/nesnmpd_helper --warm-cache"),
            unittest.mock.call("/etc/init.d/snmpd start"),
        ], shell.await_args_list)
        execute.assert_awaited_once_with(
            "/usr/bin/snmpget", "-v2c", "-c", "_nee_internal_warmup_",
            "-t", "5", "-r", "2", "127.0.0.1",
            "1.3.6.1.4.1.2000.1.1.1.0",
        )

    async def test_restore_leaves_disabled_daemon_stopped(self):
        with patch.object(
                functions.nw_functions, "read_services",
                AsyncMock(return_value=(0, 0, 0))), patch.object(
                functions, "write_snmp_config") as write_config, patch.object(
                functions.utils, "shell", AsyncMock()) as shell:
            restored = await functions.restore_snmp()

        self.assertTrue(restored)
        write_config.assert_not_called()
        shell.assert_not_awaited()

    async def test_restore_reports_daemon_start_failure(self):
        with patch.object(
                functions.nw_functions, "read_services",
                AsyncMock(return_value=(0, 1, 0))), patch.object(
                functions.os, "makedirs"), patch.object(
                functions, "write_snmp_config"), patch.object(
                functions, "write_snmp_v3_user"), patch.object(
                functions.utils, "shell",
                AsyncMock(side_effect=[(0, ""), (1, "failed")])):
            restored = await functions.restore_snmp()

        self.assertFalse(restored)

    async def test_apply_restarts_enabled_daemon_with_new_config(self):
        with patch.object(
                functions.nw_functions, "read_services",
                AsyncMock(return_value=(1, 1, 0))), patch.object(
                functions.nw_functions, "write_services",
                AsyncMock()) as write_services, patch.object(
                functions.os, "makedirs"), patch.object(
                functions, "write_snmp_config") as write_config, patch.object(
                functions, "write_snmp_v3_user") as write_v3, patch.object(
                functions.utils, "shell",
                AsyncMock(side_effect=[(0, ""), (0, ""), (0, "")])) as shell, \
                patch.object(functions.utils, "exec_command",
                             AsyncMock(return_value=(0, ""))) as execute:
            applied = await functions.apply_snmp_configuration(True)

        self.assertTrue(applied)
        write_config.assert_called_once_with()
        write_v3.assert_called_once_with()
        self.assertEqual(
            [
                unittest.mock.call("/etc/init.d/snmpd stop"),
                unittest.mock.call(
                    "/usr/bin/nesnmpd_helper --warm-cache"
                ),
                unittest.mock.call("/etc/init.d/snmpd start"),
            ],
            shell.await_args_list,
        )
        write_services.assert_awaited_once_with(1, 1, 0)
        execute.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
