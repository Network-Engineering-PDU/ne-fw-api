import asyncio
import json
import os
import stat
import tempfile
import unittest
from unittest import mock

from pydantic import ValidationError

from ttne.app.email_web import models, routers, store


class EmailWebTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.directory.name, "email_web.json")

    def tearDown(self):
        self.directory.cleanup()

    def test_defaults(self):
        config = store.load_config(self.path)
        self.assertEqual("http", config.web_protocol)
        self.assertEqual(80, config.web_port)
        self.assertEqual(587, config.smtp_port)
        self.assertEqual("none", config.smtp_auth)

    def test_atomic_save_and_reload_with_private_permissions(self):
        config = models.EmailWebStoredConfig(
            web_protocol="https",
            web_port=443,
            smtp_server="smtp.example.com",
            smtp_port=587,
            smtp_auth="login",
            from_address="pdu@example.com",
            password="secret-password",
            recipients=["noc@example.com"],
        )
        store.save_config(config, self.path)
        self.assertEqual(config, store.load_config(self.path))
        self.assertEqual(0o600, stat.S_IMODE(os.stat(self.path).st_mode))
        with open(self.path, "r", encoding="utf-8") as config_file:
            self.assertEqual("secret-password", json.load(config_file)["password"])

    def test_rejects_bad_ports_servers_addresses_and_duplicates(self):
        with self.assertRaises(ValidationError):
            models.EmailWebStoredConfig(web_port=0)
        with self.assertRaises(ValidationError):
            models.EmailWebStoredConfig(smtp_server="smtp;command")
        with self.assertRaises(ValidationError):
            models.EmailWebStoredConfig(from_address="not-an-address")
        with self.assertRaises(ValidationError):
            models.EmailWebStoredConfig(
                recipients=["noc@example.com", "NOC@example.com"]
            )

    def test_view_never_exposes_password(self):
        config = models.EmailWebStoredConfig(password="private")
        view = models.view_from_stored(config)
        self.assertTrue(view.password_configured)
        self.assertNotIn("password", view.dict())

    def test_put_preserves_hidden_password_and_none_auth_clears_it(self):
        current = models.EmailWebStoredConfig(
            smtp_auth="login", password="private"
        )
        saved = []
        update = models.EmailWebUpdate(
            web_protocol="http",
            web_port=80,
            smtp_port=587,
            smtp_auth="login",
        )
        with mock.patch.object(store, "load_config", return_value=current), \
                mock.patch.object(store, "save_config", side_effect=saved.append):
            view = asyncio.run(routers.put_email_web(update))
        self.assertTrue(view.password_configured)
        self.assertEqual("private", saved[0].password)

        update.smtp_auth = "none"
        saved.clear()
        with mock.patch.object(store, "load_config", return_value=current), \
                mock.patch.object(store, "save_config", side_effect=saved.append):
            view = asyncio.run(routers.put_email_web(update))
        self.assertFalse(view.password_configured)
        self.assertEqual("", saved[0].password)


if __name__ == "__main__":
    unittest.main()
