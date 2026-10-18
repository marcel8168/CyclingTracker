"""Tests for foreground ride-service sensor persistence."""

import os
import tempfile
import unittest

from cycling_tracker.models.database import Database
from cycling_tracker.services.ride_service import _record_heart_rate


class RideServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = Database(os.path.join(self.temp_dir.name, 'rides.db'))
        self.db.open()
        self.ride_id = self.db.create_ride()

    def tearDown(self):
        self.db.close()
        self.temp_dir.cleanup()

    def test_records_queued_heart_rate_measurement(self):
        timestamp = '2026-10-18T19:20:00+00:00'

        _record_heart_rate(self.db, self.ride_id, (143, timestamp))

        samples = self.db.get_heart_rate_samples(self.ride_id)
        self.assertEqual(len(samples), 1)
        self.assertEqual(samples[0]['heart_rate'], 143)
        self.assertEqual(samples[0]['timestamp'], timestamp)


if __name__ == '__main__':
    unittest.main()
