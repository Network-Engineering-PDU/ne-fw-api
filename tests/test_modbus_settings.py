import json
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock

# Avoid pulling in fastapi-heavy or device-only modules not needed by this test.
sys.modules.setdefault("ttgateway", MagicMock())
sys.modules.setdefault("ttgateway.commands", MagicMock())
sys.modules.setdefault("ttgateway.config", MagicMock())

from ttne.app.settings import functions, models


class ReadModbusSettingsTest(unittest.IsolatedAsyncioTestCase):
    """modbus_server asks for these settings over HTTP as soon as it starts,
    and its RTU thread used to call exit() -- killing its unrelated TCP
    server too -- whenever the address came back -1."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.directory.name, "modbus_config.json")
        self.old_file = functions.MODBUS_FILE
        functions.MODBUS_FILE = self.path

    def tearDown(self):
        functions.MODBUS_FILE = self.old_file
        self.directory.cleanup()

    async def test_missing_file_gives_the_defaults_and_creates_it(self):
        self.assertFalse(os.path.isfile(self.path))
        settings = await functions.read_modbus_settings()
        self.assertEqual(functions.DEFAULT_MODBUS_SETTINGS, settings)
        with open(self.path) as f:
            self.assertEqual(functions.DEFAULT_MODBUS_SETTINGS, json.load(f))

    async def test_unreadable_file_resets_to_the_defaults(self):
        with open(self.path, "w") as f:
            f.write("not valid json")
        settings = await functions.read_modbus_settings()
        self.assertEqual(functions.DEFAULT_MODBUS_SETTINGS, settings)

    async def test_stored_settings_are_returned_unchanged(self):
        custom = {
            "addr": 42,
            "baud_rate": 9600,
            "parity": "E",
            "stop_bits": 2,
            "tcp_eth1_enabled": False,
            "tcp_eth2_enabled": True,
        }
        await functions.write_modbus_settings(custom)
        settings = await functions.read_modbus_settings()
        self.assertEqual(custom, {key: settings[key] for key in custom})

    async def test_partial_write_keeps_the_other_defaults(self):
        await functions.write_modbus_settings({"addr": 7})
        settings = await functions.read_modbus_settings()
        self.assertEqual(7, settings["addr"])
        self.assertEqual(115200, settings["baud_rate"])

    async def test_read_modbus_returns_just_the_address(self):
        await functions.write_modbus_settings({"addr": 9})
        self.assertEqual(9, await functions.read_modbus())

    async def test_write_modbus_only_touches_the_address(self):
        await functions.write_modbus_settings({"baud_rate": 9600})
        await functions.write_modbus(5)
        settings = await functions.read_modbus_settings()
        self.assertEqual(5, settings["addr"])
        self.assertEqual(9600, settings["baud_rate"])

    async def test_new_settings_default_to_a_slave_with_both_485_ports_on(self):
        await functions.write_modbus_settings({"addr": 3})
        settings = await functions.read_modbus_settings()
        self.assertEqual("slave", settings["role"])
        self.assertTrue(settings["rtu_port1_enabled"])
        self.assertTrue(settings["rtu_port2_enabled"])
        self.assertEqual((2, 16), (settings["scan_first"], settings["scan_last"]))

    async def test_invalid_stored_value_falls_back_to_its_default_only(self):
        # Older screens accepted addresses up to 255; Modbus RTU stops at 247.
        await functions.write_modbus_settings({"addr": 250, "baud_rate": 9600})
        settings = await functions.read_modbus_settings()
        self.assertEqual(functions.DEFAULT_MODBUS_ADDR, settings["addr"])
        self.assertEqual(9600, settings["baud_rate"])

    async def test_port_control_is_never_stored(self):
        await functions.write_modbus_settings({"rtu_port_control": True})
        with open(self.path) as f:
            self.assertNotIn("rtu_port_control", json.load(f))


class ModbusSettingsRulesTest(unittest.TestCase):

    def settings(self, **changes):
        settings = dict(functions.DEFAULT_MODBUS_SETTINGS)
        settings["rtu_port_control"] = False
        settings.update(changes)
        return settings

    def test_slave_settings_are_accepted(self):
        self.assertIsNone(models.modbus_settings_error(self.settings()))

    def test_master_outside_its_scan_range_is_accepted(self):
        self.assertIsNone(models.modbus_settings_error(
            self.settings(role="master", addr=1, scan_first=2, scan_last=16)))

    def test_master_inside_its_scan_range_is_refused(self):
        error = models.modbus_settings_error(
            self.settings(role="master", addr=5, scan_first=2, scan_last=16))
        self.assertIn("own number (5)", error)

    def test_master_with_reversed_scan_range_is_refused(self):
        self.assertIsNotNone(models.modbus_settings_error(
            self.settings(role="master", addr=1, scan_first=20, scan_last=10)))

    def test_master_needs_a_485_port_when_ports_can_be_switched(self):
        both_off = dict(rtu_port1_enabled=False, rtu_port2_enabled=False,
                        role="master")
        self.assertIsNotNone(models.modbus_settings_error(
            self.settings(rtu_port_control=True, **both_off)))
        # Without per-port control both jacks stay live, so it's fine.
        self.assertIsNone(models.modbus_settings_error(
            self.settings(rtu_port_control=False, **both_off)))

    def test_model_rejects_out_of_range_values(self):
        for field, value in (("addr", 0), ("addr", 248), ("role", "boss"),
                             ("scan_last", 300), ("timeout_ms", 150),
                             ("poll_interval_s", 3), ("offline_after", 4)):
            with self.subTest(field=field, value=value):
                with self.assertRaises(ValueError):
                    models.Modbus(**{field: value})


class ModbusServiceTest(unittest.IsolatedAsyncioTestCase):
    """After a reboot the services file can say Modbus is on while no
    modbus_server runs; start, stop and restore must look at the daemon."""

    def patches(self, services, shell_results):
        from unittest.mock import AsyncMock, patch
        read = patch.object(functions.nw_functions, "read_services",
                            AsyncMock(return_value=services))
        write = patch.object(functions.nw_functions, "write_services",
                             AsyncMock())
        shell = patch.object(functions.utils, "shell",
                             AsyncMock(side_effect=shell_results))
        return read, write, shell

    async def run_with(self, func, services, shell_results):
        read, write, shell = self.patches(services, shell_results)
        with read, write as write_mock, shell as shell_mock:
            result = await func()
        commands = [c.args[0] for c in shell_mock.await_args_list]
        return result, write_mock, commands

    async def test_start_launches_daemon_when_flag_is_on_but_nothing_runs(self):
        result, write, commands = await self.run_with(
            functions.start_modbus, (0, 0, 1), [(1, ""), (0, "")])
        self.assertTrue(result)
        write.assert_not_awaited()
        self.assertEqual(["pidof modbus_server",
                          "/etc/init.d/modbus_server start"], commands)

    async def test_start_does_not_launch_a_second_daemon(self):
        result, _write, commands = await self.run_with(
            functions.start_modbus, (0, 0, 1), [(0, "123")])
        self.assertTrue(result)
        self.assertEqual(["pidof modbus_server"], commands)

    async def test_start_saves_the_flag_when_it_was_off(self):
        result, write, _commands = await self.run_with(
            functions.start_modbus, (1, 0, 0), [(1, ""), (0, "")])
        self.assertTrue(result)
        write.assert_awaited_once_with(1, 0, 1)

    async def test_stop_kills_a_daemon_even_when_flag_is_off(self):
        result, write, commands = await self.run_with(
            functions.stop_modbus, (0, 0, 0), [(0, "123"), (0, "")])
        self.assertTrue(result)
        write.assert_not_awaited()
        self.assertEqual(["pidof modbus_server",
                          "/etc/init.d/modbus_server stop"], commands)

    async def test_restore_starts_enabled_modbus_after_boot(self):
        result, _write, commands = await self.run_with(
            functions.restore_modbus, (0, 0, 1), [(1, ""), (0, "")])
        self.assertTrue(result)
        self.assertEqual(["pidof modbus_server",
                          "/etc/init.d/modbus_server start"], commands)

    async def test_restore_leaves_disabled_modbus_stopped(self):
        result, _write, commands = await self.run_with(
            functions.restore_modbus, (0, 0, 0), [])
        self.assertTrue(result)
        self.assertEqual([], commands)

    async def test_restore_reports_a_failed_start(self):
        result, _write, _commands = await self.run_with(
            functions.restore_modbus, (0, 0, 1), [(1, ""), (1, "failed")])
        self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()
