import json
import os
import stat
import tempfile
import unittest

from ttne.snmp_config import write_snmp_config


TEMPLATE = """agentAddress  udp:161
override .1.3.6.1.2.1.1.4.0 octet_str ""
override .1.3.6.1.2.1.1.5.0 octet_str "NET-POWER"
override .1.3.6.1.2.1.1.6.0 octet_str ""
rocommunity public
rwcommunity private default .1.3.6.1.4.1.2000.1
pass_persist .1.3.6.1.4.1.2000.1 /usr/bin/nesnmpd_helper
"""


class SnmpSettingsTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.source = os.path.join(self.directory.name, "template.conf")
        self.destination = os.path.join(self.directory.name, "snmpd.conf")
        self.settings = os.path.join(self.directory.name, "settings.json")
        self.nms = os.path.join(self.directory.name, "nms")
        with open(self.source, "w", encoding="utf-8") as config_file:
            config_file.write(TEMPLATE)

    def tearDown(self):
        self.directory.cleanup()

    def test_renders_validated_settings_and_escapes_system_fields(self):
        with open(self.settings, "w", encoding="utf-8") as settings_file:
            json.dump({
                "detailed_settings": {
                    "port": 1161,
                    "snmp_v1_v2c": {
                        "read_community": "monitor",
                        "write_community": "control",
                    },
                },
            }, settings_file)
        with open(self.nms, "w", encoding="utf-8") as nms_file:
            nms_file.write('PDU "A"\nops@example.test\nRack\\One')

        write_snmp_config(
            self.source, self.destination, self.settings, self.nms
        )
        with open(self.destination, "r", encoding="utf-8") as config_file:
            rendered = config_file.read()
        self.assertIn("agentAddress  udp:1161", rendered)
        self.assertIn("rocommunity monitor", rendered)
        self.assertIn(
            "rwcommunity control default .1.3.6.1.4.1.2000.1", rendered
        )
        self.assertIn('octet_str "PDU \\"A\\""', rendered)
        self.assertIn('octet_str "Rack\\\\One"', rendered)
        self.assertEqual(
            0o600, stat.S_IMODE(os.stat(self.destination).st_mode)
        )

    def test_invalid_port_and_community_use_safe_defaults(self):
        with open(self.settings, "w", encoding="utf-8") as settings_file:
            json.dump({
                "detailed_settings": {
                    "port": 70000,
                    "snmp_v1_v2c": {
                        "read_community": "bad value\nrwcommunity attacker",
                        "write_community": "Private",
                    },
                },
            }, settings_file)
        write_snmp_config(
            self.source, self.destination, self.settings, self.nms
        )
        with open(self.destination, "r", encoding="utf-8") as config_file:
            rendered = config_file.read()
        self.assertIn("agentAddress  udp:161", rendered)
        self.assertIn("rocommunity public", rendered)
        self.assertIn(
            "rwcommunity private default .1.3.6.1.4.1.2000.1", rendered
        )
        self.assertNotIn("attacker", rendered)

    def test_equal_read_and_write_communities_are_separated(self):
        with open(self.settings, "w", encoding="utf-8") as settings_file:
            json.dump({
                "detailed_settings": {
                    "snmp_v1_v2c": {
                        "read_community": "same",
                        "write_community": "same",
                    },
                },
            }, settings_file)
        write_snmp_config(
            self.source, self.destination, self.settings, self.nms
        )
        with open(self.destination, "r", encoding="utf-8") as config_file:
            rendered = config_file.read()
        self.assertIn("rocommunity same", rendered)
        self.assertIn(
            "rwcommunity private default .1.3.6.1.4.1.2000.1",
            rendered,
        )

    def test_boolean_port_and_unsafe_nms_characters_are_sanitized(self):
        with open(self.settings, "w", encoding="utf-8") as settings_file:
            json.dump({
                "detailed_settings": {
                    "port": True,
                },
            }, settings_file)
        with open(self.nms, "w", encoding="utf-8") as nms_file:
            nms_file.write(("é" * 200) + "\0\ncontact\nlocation")

        write_snmp_config(
            self.source, self.destination, self.settings, self.nms
        )
        with open(self.destination, "r", encoding="utf-8") as config_file:
            rendered = config_file.read()
        self.assertIn("agentAddress  udp:161", rendered)
        self.assertNotIn("\0", rendered)


if __name__ == "__main__":
    unittest.main()
