import json
import os
import stat
import tempfile
import unittest

from ttne.app.network import models, snmp_settings_store


def basic_config():
    return models.SnmpConfig(
        beep=True,
        relay=False,
        trap_alarm=True,
        email_alarm=False,
        refresh_period=60,
        life_time=240,
        datetime="2026-08-15 00:00:00",
        modbus_address=1,
    )


def detailed_config(user="operator", auth="AuthPass123",
                    privacy="PrivPass123"):
    return models.SnmpDetailedConfig(
        port=161,
        trap=models.SnmpTrapConfig(alarm=True),
        snmp_v1_v2c=models.SnmpV1Config(
            read_community="public", write_community="private"
        ),
        snmp_v3=models.Snmpv3Config(
            usm_user=user,
            security_level="authPriv",
            access_right="readWrite",
            auth_algorithm="SHA",
            auth_pwd=auth,
            privacy_algorithm="AES",
            privacy_pwd=privacy,
        ),
        version="V3",
    )


class SnmpSettingsStoreTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.directory.name, "snmp.json")

    def tearDown(self):
        self.directory.cleanup()

    def test_atomic_save_load_and_private_permissions(self):
        basic = basic_config()
        detailed = detailed_config()
        snmp_settings_store.save(self.path, basic, detailed)
        loaded_basic, loaded_detailed = snmp_settings_store.load(
            self.path, basic_config(), detailed_config(user="fallback")
        )
        self.assertEqual(basic, loaded_basic)
        self.assertEqual(detailed, loaded_detailed)
        self.assertEqual(0o600, stat.S_IMODE(os.stat(self.path).st_mode))
        with open(self.path, "r", encoding="utf-8") as config_file:
            self.assertEqual(
                "AuthPass123",
                json.load(config_file)["detailed_settings"]["snmp_v3"][
                    "auth_pwd"
                ],
            )

    def test_corrupt_file_uses_supplied_defaults(self):
        with open(self.path, "w", encoding="utf-8") as config_file:
            config_file.write("not-json")
        basic = basic_config()
        detailed = detailed_config()
        self.assertEqual(
            (basic, detailed),
            snmp_settings_store.load(self.path, basic, detailed),
        )

    def test_masked_v3_passwords_are_preserved_only_for_same_user(self):
        current = detailed_config()
        masked = detailed_config(auth="", privacy="")
        merged = snmp_settings_store.preserve_v3_secrets(current, masked)
        self.assertEqual("AuthPass123", merged.snmp_v3.auth_pwd)
        self.assertEqual("PrivPass123", merged.snmp_v3.privacy_pwd)

        changed_user = detailed_config(
            user="replacement", auth="", privacy=""
        )
        merged = snmp_settings_store.preserve_v3_secrets(
            current, changed_user
        )
        self.assertEqual("", merged.snmp_v3.auth_pwd)
        self.assertEqual("", merged.snmp_v3.privacy_pwd)


if __name__ == "__main__":
    unittest.main()
