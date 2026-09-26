import os
import tempfile
import unittest

from pydantic import ValidationError

from ttne.app.display_config import models, store


class DisplayConfigTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.directory.name, ".cmdisplay.config")

    def tearDown(self):
        self.directory.cleanup()

    def test_missing_file_gives_defaults(self):
        config = store.load_config(self.path)
        self.assertEqual(2, config.rotation)
        self.assertEqual(5, config.inactivity_time)
        self.assertFalse(config.skip_login)

    def test_reads_the_file_written_by_the_display(self):
        # Exact format written by cmdisplay's config.c
        with open(self.path, "w") as f:
            f.write("rotation=3\ninactivity_time=10\nskip_login=1\n"
                    "pdu_company=ACME\npdu_rack=R1\npdu_system=\n"
                    "pdu_ups=\npdu_elec_board=\npdu_breaker=\n"
                    "pdu_service=A=B\n")
        config = store.load_config(self.path)
        self.assertEqual(3, config.rotation)
        self.assertEqual(10, config.inactivity_time)
        self.assertTrue(config.skip_login)
        self.assertEqual("ACME", config.pdu_company)
        self.assertEqual("A=B", config.pdu_service)

    def test_roundtrip_and_format(self):
        config = models.DisplayConfig(rotation=3, inactivity_time=7,
                                      skip_login=True, pdu_rack="Rack 4")
        store.save_config(config, self.path)
        self.assertEqual(config, store.load_config(self.path))
        with open(self.path) as f:
            lines = f.read().splitlines()
        self.assertEqual(["rotation=3", "inactivity_time=7", "skip_login=1"],
                         lines[:3])
        self.assertIn("pdu_rack=Rack 4", lines)
        self.assertFalse(os.path.exists(self.path + ".tmp"))

    def test_rejects_bad_values(self):
        for kwargs in ({"rotation": 4}, {"rotation": -1},
                       {"inactivity_time": 0}, {"inactivity_time": 301},
                       {"pdu_rack": "a\nrotation=0"},
                       {"pdu_ups": "x" * 256}):
            with self.assertRaises(ValidationError, msg=str(kwargs)):
                models.DisplayConfig(**kwargs)

    def test_out_of_range_file_values_fall_back_to_defaults(self):
        with open(self.path, "w") as f:
            f.write("rotation=9\ninactivity_time=abc\n")
        self.assertEqual(models.DisplayConfig(), store.load_config(self.path))


if __name__ == "__main__":
    unittest.main()
