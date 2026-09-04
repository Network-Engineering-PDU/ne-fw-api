import unittest

from ttne import license as pdu_license


class LicensePayloadTest(unittest.TestCase):

    def test_legacy_payload_defaults_wifi_to_unlicensed(self):
        self.assertEqual(
            ("ABC123", 2000000000, "B2", False),
            pdu_license.parse_license_text("ABC123,2000000000,B2"),
        )

    def test_wifi_is_an_independent_signed_flag(self):
        self.assertEqual(
            ("ABC123", 2000000000, "A1", True),
            pdu_license.parse_license_text("ABC123,2000000000,A1,1"),
        )
        self.assertEqual(
            ("ABC123", 2000000000, "B2", False),
            pdu_license.parse_license_text("ABC123,2000000000,B2,0"),
        )

    def test_invalid_payload_is_rejected(self):
        invalid_payloads = (
            "ABC123,2000000000,C1,1",
            "ABC123,2000000000,B2,yes",
            "ABC123,not-an-epoch,B2,1",
            "ABC123,2000000000,B2,1,extra",
        )
        for payload in invalid_payloads:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                pdu_license.parse_license_text(payload)

    def test_outlet_capabilities_are_derived_independently(self):
        self.assertEqual({
            "type_id": "A2",
            "wifi_licensed": True,
            "outlet_switch_licensed": False,
            "outlet_metering_licensed": True,
        }, pdu_license.license_info("A2", True))


if __name__ == "__main__":
    unittest.main()
