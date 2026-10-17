"""Tests for standard BLE Heart Rate Service payload decoding."""

import unittest

from cycling_tracker.ble.hr_monitor import parse_heart_rate_measurement


class HeartRatePayloadTests(unittest.TestCase):
    def test_decodes_uint8_measurement(self):
        self.assertEqual(parse_heart_rate_measurement(bytes([0x00, 147])), 147)

    def test_decodes_uint16_measurement(self):
        self.assertEqual(
            parse_heart_rate_measurement(bytes([0x01, 0x2c, 0x01])), 300
        )

    def test_rejects_incomplete_measurement(self):
        with self.assertRaises(ValueError):
            parse_heart_rate_measurement(bytes([0x01, 10]))


if __name__ == '__main__':
    unittest.main()
