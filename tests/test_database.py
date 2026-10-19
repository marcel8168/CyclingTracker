"""Tests for local ride and sensor persistence."""

import os
import sqlite3
import stat
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from cycling_tracker.models.database import Database, _default_db_path


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

    @unittest.skipUnless(os.name == 'posix', 'POSIX file permissions required')
    def test_database_file_is_owner_only(self):
        mode = stat.S_IMODE(os.stat(self.db.db_path).st_mode)

        self.assertEqual(mode, 0o600)

    @unittest.skipUnless(os.name == 'posix', 'POSIX file permissions required')
    def test_open_restricts_existing_database_file_permissions(self):
        self.db.close()
        os.chmod(self.db.db_path, 0o644)

        self.db.open()

        mode = stat.S_IMODE(os.stat(self.db.db_path).st_mode)
        self.assertEqual(mode, 0o600)

    @unittest.skipUnless(os.name == 'posix', 'POSIX file permissions required')
    def test_default_database_directory_is_owner_only(self):
        from unittest import mock

        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = os.path.join(temp_dir, 'project')
            module_file = os.path.join(
                project_root, 'cycling_tracker', 'models', 'database.py'
            )
            os.makedirs(os.path.dirname(module_file))
            with mock.patch(
                'cycling_tracker.models.database.__file__', module_file
            ), mock.patch('cycling_tracker.models.database.platform', 'linux'):
                db_path = _default_db_path()

            mode = stat.S_IMODE(os.stat(os.path.dirname(db_path)).st_mode)
            self.assertEqual(mode, 0o700)

    def test_discard_removes_all_samples(self):
        ride_id = self.db.create_ride()
        self.db.insert_sample(ride_id, 51.5, -0.12)
        self.db.insert_heart_rate(ride_id, 142)

        self.db.discard_ride(ride_id)

        self.assertIsNone(self.db.get_ride(ride_id))
        self.assertEqual(self.db.get_samples(ride_id), [])
        self.assertEqual(self.db.get_heart_rate_samples(ride_id), [])

    def test_rejects_invalid_heart_rate(self):
        ride_id = self.db.create_ride()
        with self.assertRaises(ValueError):
            self.db.insert_heart_rate(ride_id, 0)

    def test_persists_application_settings(self):
        self.db.set_setting('ble_device_address', '00:11:22:33:44:55')
        service_db = Database(self.db.db_path)
        service_db.open()
        try:
            selected_address = service_db.get_setting('ble_device_address')
        finally:
            service_db.close()

        self.assertEqual(
            selected_address,
            '00:11:22:33:44:55',
        )
        self.assertIsNone(self.db.get_setting('missing'))

    def test_update_ride_elapsed_commits_without_leaving_transaction_open(self):
        ride_id = self.db.create_ride()
        self.db.update_ride_elapsed(ride_id, 42)

        other = sqlite3.connect(self.db.db_path, timeout=0.2)
        try:
            other.execute(
                'INSERT INTO samples '
                '(ride_id, timestamp, latitude, longitude, altitude, speed, '
                'bearing, accuracy, heart_rate, source) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (ride_id, '2024-01-01T00:00:00Z', 51.5, -0.12, None, 0.0, None, None, None, 'gps')
            )
            other.commit()
        finally:
            other.close()

        self.assertEqual(self.db.get_ride(ride_id)['total_elapsed_s'], 42)

    def test_concurrent_connections_persist_all_location_samples(self):
        ride_id = self.db.create_ride()
        connection_count = 3
        samples_per_connection = 40
        start_writes = Barrier(connection_count)

        def insert_samples(connection_id):
            connection = Database(self.db.db_path)
            connection.open()
            try:
                start_writes.wait(timeout=5)
                for sample_number in range(samples_per_connection):
                    connection.insert_sample(
                        ride_id,
                        latitude=51.5 + connection_id / 1000,
                        longitude=-0.12,
                        timestamp=(
                            f'2026-10-18T19:{connection_id:02d}:'
                            f'{sample_number:02d}+00:00'
                        ),
                    )
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=connection_count) as executor:
            tasks = [
                executor.submit(insert_samples, connection_id)
                for connection_id in range(connection_count)
            ]
            for task in tasks:
                task.result(timeout=30)

        self.assertEqual(
            self.db.get_sample_count(ride_id),
            connection_count * samples_per_connection,
        )

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
            self.assertEqual(version, 4)
            self.assertIsNotNone(table)
        finally:
            upgraded.close()

    def test_migrates_existing_samples_to_cascade_on_ride_delete(self):
        legacy_path = os.path.join(self.temp_dir.name, 'legacy_samples.db')
        legacy = sqlite3.connect(legacy_path)
        legacy.executescript(
            """
            CREATE TABLE schema_version (version INTEGER NOT NULL);
            INSERT INTO schema_version (version) VALUES (2);
            CREATE TABLE rides (
                id INTEGER PRIMARY KEY,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                status TEXT NOT NULL DEFAULT 'active',
                total_distance_m REAL NOT NULL DEFAULT 0.0,
                total_elapsed_s INTEGER NOT NULL DEFAULT 0,
                notes TEXT
            );
            CREATE TABLE samples (
                id INTEGER PRIMARY KEY,
                ride_id INTEGER NOT NULL,
                timestamp TEXT NOT NULL,
                latitude REAL NOT NULL,
                longitude REAL NOT NULL,
                altitude REAL,
                speed REAL,
                bearing REAL,
                accuracy REAL,
                heart_rate INTEGER,
                source TEXT NOT NULL DEFAULT 'gps',
                FOREIGN KEY (ride_id) REFERENCES rides(id)
            );
            INSERT INTO rides (id, started_at) VALUES (1, '2026-01-01T00:00:00Z');
            INSERT INTO samples (ride_id, timestamp, latitude, longitude)
                VALUES (1, '2026-01-01T00:00:01Z', 51.5, -0.12);
            """
        )
        legacy.commit()
        legacy.close()

        upgraded = Database(legacy_path)
        upgraded.open()
        try:
            foreign_key = upgraded.conn.execute(
                'PRAGMA foreign_key_list(samples)'
            ).fetchone()
            self.assertEqual(foreign_key['on_delete'], 'CASCADE')
            self.assertEqual(upgraded.get_sample_count(1), 1)

            upgraded.conn.execute('DELETE FROM rides WHERE id = 1')
            upgraded.conn.commit()
            self.assertEqual(upgraded.get_sample_count(1), 0)
        finally:
            upgraded.close()

    def test_migrates_missing_total_elapsed_column(self):
        legacy_path = os.path.join(self.temp_dir.name, 'legacy_rides.db')
        legacy = sqlite3.connect(legacy_path)
        legacy.executescript(
            """
            CREATE TABLE schema_version (version INTEGER NOT NULL);
            INSERT INTO schema_version (version) VALUES (2);
            CREATE TABLE rides (
                id INTEGER PRIMARY KEY,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                status TEXT NOT NULL DEFAULT 'active',
                total_distance_m REAL NOT NULL DEFAULT 0.0,
                notes TEXT
            );
            INSERT INTO rides (id, started_at) VALUES (1, '2026-01-01T00:00:00Z');
            """
        )
        legacy.commit()
        legacy.close()

        upgraded = Database(legacy_path)
        upgraded.open()
        try:
            columns = {
                row['name']
                for row in upgraded.conn.execute('PRAGMA table_info(rides)')
            }
            self.assertIn('total_elapsed_s', columns)
            self.assertEqual(upgraded.get_ride(1)['total_elapsed_s'], 0)
        finally:
            upgraded.close()


if __name__ == '__main__':
    unittest.main()
