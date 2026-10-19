"""Tests for foreground ride-service sensor persistence."""

from cycling_tracker.services.ride_service import _record_heart_rate


def test_records_queued_heart_rate_measurement(database):
    ride_id = database.create_ride()
    timestamp = '2026-10-18T19:20:00+00:00'

    _record_heart_rate(database, ride_id, (143, timestamp))

    samples = database.get_heart_rate_samples(ride_id)
    assert len(samples) == 1
    assert samples[0]['heart_rate'] == 143
    assert samples[0]['timestamp'] == timestamp
