"""Tests for ride lifecycle transitions and persistence."""

import os
import tempfile
import unittest
from unittest import mock

from cycling_tracker.models.database import Database
from cycling_tracker.ride_manager import RideManager


class RideManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = Database(os.path.join(self.temp_dir.name, 'rides.db'))
        self.manager = RideManager(db=self.db)

        self.platform_patcher = mock.patch(
            'cycling_tracker.ride_manager.platform', 'linux'
        )
        self.platform_patcher.start()
        self.addCleanup(self.platform_patcher.stop)

        self.location_start = mock.patch.object(self.manager.location, 'start')
        self.location_stop = mock.patch.object(self.manager.location, 'stop')
        self.location_start.start()
        self.location_stop.start()
        self.addCleanup(self.location_start.stop)
        self.addCleanup(self.location_stop.stop)

        self.timers = []

        def schedule_interval(*_args):
            timer = mock.Mock()
            self.timers.append(timer)
            return timer

        self.clock_patcher = mock.patch(
            'cycling_tracker.ride_manager.Clock.schedule_interval',
            side_effect=schedule_interval,
        )
        self.clock_patcher.start()
        self.addCleanup(self.clock_patcher.stop)
        self.addCleanup(self.temp_dir.cleanup)
        self.addCleanup(self.db.close)

    def test_start_pause_resume_and_stop_persist_ride(self):
        with mock.patch(
            'cycling_tracker.ride_manager.time.monotonic',
            side_effect=[100, 105, 200, 203],
        ):
            self.assertTrue(self.manager.start())
            ride_id = self.manager.ride_id
            self.assertEqual(self.db.get_ride(ride_id)['status'], 'active')

            self.manager._on_location({
                'latitude': 51.5,
                'longitude': -0.12,
                'altitude': 18.0,
                'speed': 4.0,
                'accuracy': 3.0,
                'timestamp': '2026-10-18T19:20:00+00:00',
            })
            self.manager.record_heart_rate(
                142, timestamp='2026-10-18T19:20:01+00:00'
            )
            self.manager.pause()

            self.assertEqual(self.manager.state, 'paused')
            self.assertEqual(self.db.get_ride(ride_id)['total_elapsed_s'], 5)
            self.assertEqual(self.manager.sample_count, 1)
            self.timers[0].cancel.assert_called_once_with()

            self.manager.record_heart_rate(160)
            self.assertEqual(len(self.db.get_heart_rate_samples(ride_id)), 1)

            self.manager.resume()
            self.assertEqual(self.manager.state, 'recording')
            self.manager._on_location({
                'latitude': 51.5001,
                'longitude': -0.12,
                'altitude': 19.0,
                'speed': 5.0,
                'accuracy': 3.0,
                'timestamp': '2026-10-18T19:20:02+00:00',
            })
            self.manager.record_heart_rate(
                145, timestamp='2026-10-18T19:20:03+00:00'
            )
            self.manager.stop()

        ride = self.db.get_ride(ride_id)
        self.assertEqual(self.manager.state, 'finished')
        self.assertEqual(ride['status'], 'completed')
        self.assertEqual(ride['total_elapsed_s'], 8)
        self.assertGreater(ride['total_distance_m'], 0)
        self.assertEqual(self.db.get_sample_count(ride_id), 2)
        self.assertEqual(len(self.db.get_heart_rate_samples(ride_id)), 2)
        self.assertEqual(self.manager.sample_count, 2)
        self.assertEqual(len(self.timers), 2)
        for timer in self.timers:
            timer.cancel.assert_called_once_with()

    def test_discard_removes_ride_and_clears_metrics(self):
        self.manager.start()
        ride_id = self.manager.ride_id
        self.manager._on_location({
            'latitude': 51.5,
            'longitude': -0.12,
            'altitude': 18.0,
            'speed': 4.0,
            'accuracy': 3.0,
        })

        self.manager.discard()

        self.assertEqual(self.manager.state, 'idle')
        self.assertEqual(self.manager.ride_id, 0)
        self.assertEqual(self.manager.sample_count, 0)
        self.assertIsNone(self.db.get_ride(ride_id))
        self.assertEqual(self.db.get_samples(ride_id), [])
        self.timers[0].cancel.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
