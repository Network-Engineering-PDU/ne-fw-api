import unittest
from unittest.mock import patch

from ttne.sn_pn_generator import INVALID_PN, is_valid_pn, pn_gen


class PartNumberGeneratorTest(unittest.TestCase):
    def test_generates_documented_fourteen_character_layout(self):
        with patch("ttne.sn_pn_generator.config.BOARD_ID", 1), \
                patch("ttne.sn_pn_generator.config.REV_ID", 1):
            self.assertEqual("N000001001000G", pn_gen(0, 0, 0, 16))

    def test_encodes_output_count_as_one_base36_character(self):
        with patch("ttne.sn_pn_generator.config.BOARD_ID", "AB12"), \
                patch("ttne.sn_pn_generator.config.REV_ID", "C2"):
            self.assertEqual("N00AB120C2311W", pn_gen(3, 1, 1, 32))

    def test_rejects_values_that_do_not_fit_the_layout(self):
        with patch("ttne.sn_pn_generator.config.BOARD_ID", "1234567"):
            self.assertEqual(INVALID_PN, pn_gen(0, 0, 0, 1))
        self.assertEqual(INVALID_PN, pn_gen(4, 0, 0, 1))
        self.assertEqual(INVALID_PN, pn_gen(0, 2, 0, 1))
        self.assertEqual(INVALID_PN, pn_gen(0, 0, 2, 1))
        self.assertEqual(INVALID_PN, pn_gen(0, 0, 0, 36))

    def test_validates_new_format_and_rejects_legacy_format(self):
        self.assertTrue(is_valid_pn("N000001001000G"))
        self.assertFalse(is_valid_pn("NE0001001000"))
        self.assertFalse(is_valid_pn(INVALID_PN))


if __name__ == "__main__":
    unittest.main()
