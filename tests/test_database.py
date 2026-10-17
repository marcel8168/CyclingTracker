"""Tests for local ride and sensor persistence."""

import os
import sqlite3
import tempfile
import unittest

from cycling_tracker.models.database import Database


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = Database(os.path.join(self.temp_dir.name, 'rides.db'))
        self.db.open()

    def tearDown(self):
        self.db.close()
        self.temp_dir.cleanup()

    def test_persists_location_and_heart_rate_samples(self):
        ride_id = self.db.create_ride()
        self.db.insert_sample(
            ride_id, 51.5, -0.12, altitude=15.2, speed=4.5, accuracy=3.0
        )
        self.db.insert_heart_rate(ride_id, 142)

        self.assertEqual(self.db.get_sample_count(ride_id), 1)
        self.assertAlmostEqual(self.db.get_samples(ride_id)[0]['speed'], 4.5)
        self.assertEqual(
            self.db.get_heart_rate_samples(ride_id)[0]['heart_rate'], 142
        )

    def test_discard_removes_all_samples(self):
        ride_id = self.db.create_ride()
        self.db.insert_sample(ride_id, 51.5, -0.12)
        self.db.insert_heart_rate(ride_id, 142)

        self.db.discard_ride(ride_id)

        self.assertIsNone(self.db.get_ride(ride_id))
        self.assertEqual(self.db.get_heart_rate_samples(ride_id), [])

    def test_rejects_invalid_heart_rate(self):
        ride_id = self.db.create_ride()
        with self.assertRaises(ValueError):
            self.db.insert_heart_rate(ride_id, 0)

    def test_upgrades_existing_schema_with_heart_rate_table(self):
        legacy_path = os.path.join(self.temp_dir.name, 'legacy.db')
        legacy = sqlite3.connect(legacy_path)
        legacy.execute('CREATE TABLE schema_version (version INTEGER NOT NULL)')
        legacy.execute('INSERT INTO schema_version (version) VALUES (1)')
        legacy.commit()
        legacy.close()

        upgraded = Database(legacy_path)
        upgraded.open()
        try:
            version = upgraded.conn.execute(
                'SELECT version FROM schema_version'
            ).fetchone()['version']
            table = upgraded.conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table' AND name = 'heart_rate_samples'"
            ).fetchone()
            self.assertEqual(version, 2)
            self.assertIsNotNone(table)
        finally:
            upgraded.close()


if __name__ == '__main__':
    unittest.main()
