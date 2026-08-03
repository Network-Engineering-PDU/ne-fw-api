import json
import os
import stat
import tempfile
import unittest

from pydantic import ValidationError

from ttne.app.user_access import models, store


class UserAccessTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.directory.name, "user_access.json")

    def tearDown(self):
        self.directory.cleanup()

    def test_defaults_have_three_capacities_and_admin(self):
        config = store.load_config(self.path)
        self.assertEqual(
            ["readOnly", "control", "fullEdit"],
            [level.capacity for level in config.levels],
        )
        self.assertEqual("admin", config.users[0].name)
        self.assertEqual("Full edit", config.users[0].level)

    def test_atomic_save_and_reload(self):
        config = models.UserAccessConfig(
            levels=[
                models.AccessLevel(name="Operators", capacity="control"),
                models.AccessLevel(name="Admins", capacity="fullEdit"),
            ],
            users=[models.UserEntry(name="Ahmed", level="Admins")],
        )
        store.save_config(config, self.path)
        loaded = store.load_config(self.path)
        self.assertEqual(config, loaded)
        self.assertEqual(0o600, stat.S_IMODE(os.stat(self.path).st_mode))
        with open(self.path, "r", encoding="utf-8") as config_file:
            self.assertEqual(config.dict(), json.load(config_file))

    def test_rejects_invalid_relationships_and_unsafe_text(self):
        with self.assertRaises(ValidationError):
            models.UserAccessConfig(levels=[
                {"name": "Admin", "capacity": "fullEdit"},
                {"name": "admin", "capacity": "control"},
            ])
        with self.assertRaises(ValidationError):
            models.UserAccessConfig(
                levels=[{"name": "Admin", "capacity": "fullEdit"}],
                users=[{"name": "user", "level": "Missing"}],
            )
        with self.assertRaises(ValidationError):
            models.UserEntry(name="bad\nname", level="Admin")

    def test_rejects_configuration_without_full_edit_level(self):
        with self.assertRaises(ValidationError):
            models.UserAccessConfig(
                levels=[{"name": "Viewer", "capacity": "readOnly"}]
            )


if __name__ == "__main__":
    unittest.main()
