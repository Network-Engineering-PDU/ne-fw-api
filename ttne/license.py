"""Validation and capability mapping for signed PDU licences."""


VALID_LICENSE_TYPES = frozenset(("A1", "A2", "B1", "B2"))


def default_license_info():
    return {
        "type_id": "A1",
        "wifi_licensed": False,
        "outlet_switch_licensed": False,
        "outlet_metering_licensed": False,
    }


def parse_license_text(license_text):
    """Parse a verified payload, accepting legacy three-field licences."""
    if not isinstance(license_text, str):
        raise ValueError("License payload must be text")
    fields = license_text.split(",")
    if len(fields) not in (3, 4):
        raise ValueError("License payload has an invalid field count")

    serial_number, expiration_text, license_type = fields[:3]
    if not serial_number or license_type not in VALID_LICENSE_TYPES:
        raise ValueError("License payload contains invalid identity data")

    expiration = int(expiration_text)
    wifi_licensed = False
    if len(fields) == 4:
        if fields[3] not in ("0", "1"):
            raise ValueError("Wi-Fi license flag must be 0 or 1")
        wifi_licensed = fields[3] == "1"

    return serial_number, expiration, license_type, wifi_licensed


def license_info(license_type, wifi_licensed):
    if license_type not in VALID_LICENSE_TYPES:
        raise ValueError("Unknown outlet license type")
    return {
        "type_id": license_type,
        "wifi_licensed": bool(wifi_licensed),
        "outlet_switch_licensed": license_type in ("B1", "B2"),
        "outlet_metering_licensed": license_type in ("A2", "B2"),
    }
