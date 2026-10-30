import hashlib
import http.server
import json
import os
import tempfile
import threading
import unittest
from functools import partial
from unittest.mock import patch

from ttne.ota import config as ota_config
from ttne.ota import daemon, remote, state as ota_state, updater
from ttne.ota.http_server import HttpServerClient, HttpServerError, base_urls


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


class LocationTest(unittest.TestCase):
    def test_base_urls(self):
        self.assertEqual(["https://192.168.1.50", "http://192.168.1.50"],
                         base_urls("192.168.1.50"))
        self.assertEqual(["https://updates.example.com:8080/pdu/fw",
                          "http://updates.example.com:8080/pdu/fw"],
                         base_urls(" updates.example.com:8080/pdu/fw/ "))
        self.assertEqual(["http://10.0.0.5/fw"], base_urls("http://10.0.0.5/fw"))
        self.assertEqual(["https://[fd00::5]"], base_urls("https://[fd00::5]"))
        for invalid in ("", "ftp://10.0.0.5", "bad host", "http://user:pw@host",
                        "host:99999", "-bad.example", "http://host/fw?x=1",
                        "a" * 64 + ".example"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                base_urls(invalid)

    def test_server_picks_the_backend(self):
        cfg = dict(ota_config.DEFAULTS)
        for default in ("", "https://github.com/Network-Engineering-PDU/firmware-update"):
            applied = remote.apply_server(cfg, default)
            self.assertEqual(("github_repo", "Network-Engineering-PDU", "firmware-update", "main", ""),
                             (applied["provider"], applied["github_owner"],
                              applied["github_repo"], applied["github_ref"],
                              applied["github_path"]))
        applied = remote.apply_server(cfg, "github.com/acme/fw.git/tree/stable/pdu/")
        self.assertEqual(("acme", "fw", "stable", "pdu"),
                         (applied["github_owner"], applied["github_repo"],
                          applied["github_ref"], applied["github_path"]))
        applied = remote.apply_server(cfg, "192.168.1.50/fw")
        self.assertEqual(("http_server", "192.168.1.50/fw"),
                         (applied["provider"], applied["server_url"]))
        self.assertEqual("", remote.validate_config(applied))
        self.assertIsInstance(remote.create_client(applied), HttpServerClient)
        # Back to GitHub
        self.assertEqual("github_repo", remote.apply_server(applied, "")["provider"])
        with self.assertRaises(ValueError):
            remote.apply_server(cfg, "not a server")

    def test_intervals(self):
        for hours in (24, 168, 720, 8760):
            self.assertEqual(hours * 3600, ota_config.check_interval_seconds(
                {"check_interval_hours": hours}))
        for legacy in (1, 5, "x", None):
            self.assertEqual(24, ota_config.check_interval_hours(
                {"check_interval_hours": legacy}))


class ScheduleTest(unittest.TestCase):
    NOW = 1_800_000_000.0

    def state(self, hours_ago, **extra):
        last = "" if hours_ago is None else ota_state.datetime.fromtimestamp(
            self.NOW - hours_ago * 3600, ota_state.timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ")
        return {"last_check_time": last, "status": "idle", "last_error": "", **extra}

    def due(self, state, hours=24, since_attempt=None, enabled=True):
        cfg = {"enabled": enabled, "check_interval_hours": hours}
        return daemon.check_due(cfg, state, self.NOW, since_attempt)

    def test_interval_counts_from_the_last_check(self):
        self.assertTrue(self.due(self.state(None)))
        self.assertFalse(self.due(self.state(23)))
        self.assertTrue(self.due(self.state(25)))
        self.assertFalse(self.due(self.state(24 * 6), hours=168))
        self.assertTrue(self.due(self.state(24 * 8), hours=168))
        self.assertFalse(self.due(self.state(24 * 300), hours=8760))
        self.assertTrue(self.due(self.state(24 * 366), hours=8760))
        self.assertFalse(self.due(self.state(None), enabled=False))

    def test_restart_does_not_check_early_but_clock_going_back_does(self):
        self.assertFalse(self.due(self.state(2), since_attempt=None))
        self.assertTrue(self.due(self.state(-24 * 100)))   # last check "in the future"

    def test_failed_checks_retry_hourly(self):
        failed = self.state(2, status="failed", last_error="can not reach")
        self.assertTrue(self.due(failed, hours=720))
        self.assertFalse(self.due(failed, hours=720, since_attempt=600))
        self.assertTrue(self.due(failed, hours=720, since_attempt=3700))


class HttpServerUpdateTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        root = os.path.join(self.directory.name, "www", "fw")
        os.makedirs(root)
        self.firmware = os.urandom(300_000)
        with open(os.path.join(root, "ttfile.bin"), "wb") as out:
            out.write(self.firmware)
        self.write_metadata(root, "9.9.9", hashlib.sha256(self.firmware).hexdigest())
        handler = partial(_QuietHandler, directory=os.path.join(self.directory.name, "www"))
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.location = f"127.0.0.1:{self.server.server_port}/fw"

        ne = os.path.join(self.directory.name, "ne")
        self.patches = [
            patch.object(ota_config, "OTA_CONFIG_FILE", os.path.join(ne, "ota_config.json")),
            patch.object(ota_state, "OTA_DIR", os.path.join(ne, "ota")),
            patch.object(ota_state, "OTA_STATE_FILE", os.path.join(ne, "ota", "ota_state.json")),
            patch.object(ota_state, "OTA_DOWNLOAD_DIR", os.path.join(ne, "ota", "downloads")),
            patch.object(ota_state, "PENDING_METADATA_FILE",
                         os.path.join(ne, "ota", "pending_metadata.json")),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.server.shutdown()
        self.server.server_close()
        self.directory.cleanup()

    @staticmethod
    def write_metadata(root, version, sha):
        with open(os.path.join(root, "metadata.json"), "w") as out:
            json.dump({"firmware_version": version, "firmware_file": "ttfile.bin",
                       "sha256": sha}, out)

    def test_https_falls_back_to_http_and_downloads(self):
        client = HttpServerClient(self.location)
        metadata = client.fetch_metadata("metadata.json")
        self.assertEqual("9.9.9", metadata["firmware_version"])
        self.assertTrue(client.base.startswith("http://"))
        destination = os.path.join(self.directory.name, "firmware.bin")
        progress = []
        client.download_firmware("ttfile.bin", destination, progress.append)
        with open(destination, "rb") as source:
            self.assertEqual(self.firmware, source.read())
        self.assertEqual(100, progress[-1])

        with self.assertRaises(HttpServerError):
            HttpServerClient(self.location + "/missing").fetch_metadata("metadata.json")
        with self.assertRaises(HttpServerError):
            client.download_firmware("../secret", destination)
        with self.assertRaises(HttpServerError):     # nothing listens there
            HttpServerClient("http://127.0.0.1:9/fw").fetch_metadata("metadata.json")

    def test_check_on_a_local_server_needs_no_internet(self):
        ota_config.save_config(remote.apply_server(
            {**ota_config.DEFAULTS, "enabled": False}, self.location))
        prepared = []
        with patch.object(updater, "internet_available", return_value=False), \
                patch.object(updater.settings_functions, "get_software_version",
                             return_value="0.5.0"), \
                patch.object(updater.UpdateCoordinator, "can_check_ota",
                             return_value=(True, "")), \
                patch.object(updater.UpdateCoordinator, "can_begin",
                             return_value=(True, "")), \
                patch.object(updater.OtaUpdater, "_prepare_pending_update",
                             side_effect=lambda m: prepared.append(m) or {}):
            # Automatic updates off: the schedule doesn't check...
            updater.run_check()
            self.assertEqual([], prepared)
            # ...but "Check now" does, and the update waits for confirmation.
            updater.run_check(force=True)
            self.assertEqual(["9.9.9"], [m["firmware_version"] for m in prepared])

            # Not newer: up to date
            self.write_metadata(os.path.join(self.directory.name, "www", "fw"),
                                "0.5.0", "00")
            updater.run_check(force=True)
            self.assertEqual(1, len(prepared))
            self.assertEqual("0.5.0", ota_state.load_state()["available_version"])


if __name__ == "__main__":
    unittest.main()
