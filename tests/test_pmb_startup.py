import asyncio
import os
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from ttne.pic_bootloader import BLUart
from ttne.pmb import Pmb


class SilentUart:
    def __init__(self):
        self.sent = []

    def clean(self):
        pass

    def send_msg(self, data):
        self.sent.append(data)

    def get_byte(self, timeout=None):
        return bytes()

    def readline(self, timeout=None):
        return None


class RespondingUart(SilentUart):
    def __init__(self, responses):
        super().__init__()
        self.responses = list(responses)

    def get_byte(self, timeout=None):
        if self.responses:
            return self.responses.pop(0)
        return bytes()


class PmbStartupTest(unittest.IsolatedAsyncioTestCase):

    def test_switches_follow_the_pmb_hardware_encoding(self):
        pmb = object.__new__(Pmb)
        pmb.uart = SilentUart()
        pmb._log_switches = MagicMock()

        for raw, expected in (
            (0b0000, (0, 0, 0)),  # main, mono, Hall
            (0b0100, (0, 2, 0)),  # main, three-phase, Hall
            (0b1111, (1, 3, 1)),  # main+aux, three-phase+N, transformer
        ):
            pmb.get_uart_resp = MagicMock(return_value=("K", str(raw)))
            pmb._get_switches()
            self.assertEqual(
                (pmb.branch, pmb.sys_type, pmb.curr_type),
                expected,
            )

    async def test_bootloader_acknowledgement_still_succeeds(self):
        uart = RespondingUart([b":", b"K"])
        bootloader_uart = BLUart(uart)

        acknowledged = await bootloader_uart.write(b"request")

        self.assertTrue(acknowledged)
        self.assertEqual(uart.sent, [b"request"])

    async def test_bootloader_silent_uart_has_bounded_timeout(self):
        uart = SilentUart()
        bootloader_uart = BLUart(uart)
        bootloader_uart.RESPONSE_TIMEOUT_SECONDS = 0.02

        started = time.monotonic()
        response = await bootloader_uart.recv()
        elapsed = time.monotonic() - started

        self.assertIsNone(response)
        self.assertLess(elapsed, 0.2)

    def test_missing_pmb_version_is_not_reported_as_zero(self):
        pmb = object.__new__(Pmb)
        pmb.uart = SilentUart()

        self.assertIsNone(pmb.get_fw_version())

    async def test_missing_pmb_version_skips_firmware_update(self):
        pmb = object.__new__(Pmb)
        pmb.get_fw_version = MagicMock(return_value=None)

        with patch("ttne.pmb.PicBootloader") as bootloader:
            updated = await pmb.update_fw()

        self.assertFalse(updated)
        bootloader.assert_not_called()

    async def test_complete_firmware_update_has_overall_timeout(self):
        pmb = object.__new__(Pmb)
        pmb.uart = SilentUart()
        pmb.get_fw_version = MagicMock(return_value="1.0.0")
        pmb.reset = MagicMock(return_value=True)
        pmb.UPDATE_TIMEOUT_SECONDS = 0.02
        pmb.BOOTLOADER_SETTLE_SECONDS = 0

        never_finishes = asyncio.Event()

        async def wait_forever():
            await never_finishes.wait()

        bootloader = MagicMock()
        bootloader.load_hex = AsyncMock()
        bootloader.flash = AsyncMock(side_effect=wait_forever)

        with tempfile.TemporaryDirectory() as firmware_dir:
            firmware_file = os.path.join(firmware_dir, "pmb.hex")
            with open(firmware_file, "w") as file:
                file.write(":00000001FF\n")
            pmb.FW_DIR = firmware_dir

            with patch(
                "ttne.pmb.PicBootloader",
                return_value=bootloader,
            ):
                started = time.monotonic()
                updated = await pmb.update_fw()
                elapsed = time.monotonic() - started

        self.assertFalse(updated)
        self.assertLess(elapsed, 0.2)
        pmb.reset.assert_called_once_with()
        bootloader.flash.assert_awaited_once_with()


if __name__ == "__main__":
    unittest.main()
