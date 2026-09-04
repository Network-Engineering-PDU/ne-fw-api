import json
import os
import stat
import tempfile
import unittest

from ttne.snmp_config import write_snmp_config, write_snmp_v3_user


TEMPLATE = """agentAddress  udp:161
override .1.3.6.1.2.1.1.4.0 octet_str ""
override .1.3.6.1.2.1.1.5.0 octet_str "NET-POWER"
override .1.3.6.1.2.1.1.6.0 octet_str ""
rocommunity public
rwcommunity private default .1.3.6.1.4.1.66547.1
pass_persist .1.3.6.1.4.1.66547.1 /usr/bin/nesnmpd_helper
"""


class SnmpSettingsTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.source = os.path.join(self.directory.name, "template.conf")
        self.destination = os.path.join(self.directory.name, "snmpd.conf")
        self.settings = os.path.join(self.directory.name, "settings.json")
        self.nms = os.path.join(self.directory.name, "nms")
        self.persistent = os.path.join(
            self.directory.name, "persistent-snmpd.conf"
        )
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
            self.source, self.destination, self.settings, self.nms,
            self.persistent,
        )
        with open(self.destination, "r", encoding="utf-8") as config_file:
            rendered = config_file.read()
        self.assertIn("agentAddress  udp:1161", rendered)
        self.assertIn("com2sec neSnmpRead default monitor", rendered)
        self.assertIn("group neSnmpReadGroup v2c neSnmpRead", rendered)
        self.assertIn("com2sec neSnmpWrite default control", rendered)
        self.assertIn(
            "view neSnmpPdu included .1.3.6.1.4.1.66547.1", rendered
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
        self.assertIn("com2sec neSnmpRead default public", rendered)
        self.assertIn("com2sec neSnmpWrite default private", rendered)
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
        self.assertIn("com2sec neSnmpRead default same", rendered)
        self.assertIn("com2sec neSnmpWrite default private", rendered)

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

    def test_set_access_can_be_disabled(self):
        with open(self.settings, "w", encoding="utf-8") as settings_file:
            json.dump({
                "detailed_settings": {
                    "set_enabled": False,
                    "snmp_v1_v2c": {
                        "read_community": "monitor",
                        "write_community": "control",
                    },
                },
            }, settings_file)

        write_snmp_config(
            self.source, self.destination, self.settings, self.nms
        )

        with open(self.destination, "r", encoding="utf-8") as config_file:
            rendered = config_file.read()
        self.assertIn("com2sec neSnmpRead default monitor", rendered)
        self.assertNotIn("neSnmpWrite", rendered)

    def test_v1_and_v2c_select_distinct_security_models(self):
        for configured, expected in (
                ("V1", "v1"), ("V2c", "v2c"), ("V1/V2c", "v2c")):
            with self.subTest(version=configured):
                with open(self.settings, "w", encoding="utf-8") as settings_file:
                    json.dump({
                        "detailed_settings": {
                            "version": configured,
                            "snmp_v1_v2c": {
                                "read_community": "monitor",
                                "write_community": "control",
                            },
                        },
                    }, settings_file)
                write_snmp_config(
                    self.source, self.destination, self.settings, self.nms
                )
                with open(self.destination, "r", encoding="utf-8") as config_file:
                    rendered = config_file.read()
                self.assertIn(
                    f"group neSnmpReadGroup {expected} neSnmpRead",
                    rendered,
                )
                other = "v2c" if expected == "v1" else "v1"
                self.assertNotIn(
                    f"group neSnmpReadGroup {other} neSnmpRead",
                    rendered,
                )

    def test_v3_renders_usm_user_and_access(self):
        with open(self.settings, "w", encoding="utf-8") as settings_file:
            json.dump({
                "detailed_settings": {
                    "version": "V3",
                    "set_enabled": True,
                    "snmp_v3": {
                        "usm_user": "operator",
                        "security_level": "authPriv",
                        "access_right": "readWrite",
                        "auth_algorithm": "SHA",
                        "auth_pwd": "AuthPass123",
                        "privacy_algorithm": "AES",
                        "privacy_pwd": "PrivPass123",
                    },
                },
            }, settings_file)

        write_snmp_config(
            self.source, self.destination, self.settings, self.nms,
            self.persistent,
        )
        with open(self.destination, "r", encoding="utf-8") as config_file:
            rendered = config_file.read()
        self.assertNotIn("rocommunity", rendered)
        self.assertNotIn("rwcommunity", rendered)
        self.assertIn(
            "rwuser operator priv", rendered
        )
        self.assertIn(
            f"includeFile {self.persistent}", rendered
        )
        self.assertNotIn("createUser", rendered)

        with open(self.persistent, "w", encoding="utf-8") as config_file:
            config_file.write("engineBoots 7\nusmUser old-user-data\n")
        write_snmp_v3_user(self.settings, self.persistent)
        with open(self.persistent, "r", encoding="utf-8") as config_file:
            persistent = config_file.read()
        self.assertIn(
            'createUser operator SHA "AuthPass123" AES "PrivPass123"',
            persistent,
        )
        self.assertIn("engineBoots 7", persistent)
        self.assertNotIn("old-user-data", persistent)
        self.assertEqual(
            0o600, stat.S_IMODE(os.stat(self.persistent).st_mode)
        )

    def test_invalid_v3_credentials_do_not_restore_community_access(self):
        with open(self.settings, "w", encoding="utf-8") as settings_file:
            json.dump({
                "detailed_settings": {
                    "version": "V3",
                    "snmp_v3": {
                        "usm_user": "operator",
                        "security_level": "authPriv",
                        "auth_algorithm": "SHA",
                        "auth_pwd": "short",
                        "privacy_algorithm": "AES",
                        "privacy_pwd": "also-short",
                    },
                },
            }, settings_file)

        write_snmp_config(
            self.source, self.destination, self.settings, self.nms
        )
        with open(self.destination, "r", encoding="utf-8") as config_file:
            rendered = config_file.read()

        self.assertNotIn("rocommunity", rendered)
        self.assertNotIn("rwcommunity", rendered)
        self.assertNotIn("createUser", rendered)
        self.assertNotIn("rouser", rendered)
        self.assertNotIn("rwuser", rendered)

        write_snmp_v3_user(self.settings, self.persistent)
        with open(self.persistent, "r", encoding="utf-8") as config_file:
            self.assertNotIn("createUser", config_file.read())


if __name__ == "__main__":
    unittest.main()
