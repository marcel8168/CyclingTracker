"""Tests for ride lifecycle transitions and persistence."""

from unittest.mock import Mock

import cycling_tracker.ride_manager as ride_manager_module


def test_start_pause_resume_and_stop_persist_ride(
    ride_manager, database, monkeypatch
):
    manager, timers = ride_manager
    monkeypatch.setattr(
        ride_manager_module.time,
        'monotonic',
        Mock(side_effect=[100, 105, 200, 203]),
    )
    assert manager.start()
    ride_id = manager.ride_id
    assert database.get_ride(ride_id)['status'] == 'active'

    manager._on_location({
            'latitude': 51.5,
            'longitude': -0.12,
            'altitude': 18.0,
            'speed': 4.0,
            'accuracy': 3.0,
            'timestamp': '2026-10-18T19:20:00+00:00',
        })
    manager.record_heart_rate(142, timestamp='2026-10-18T19:20:01+00:00')
    manager.pause()

    assert manager.state == 'paused'
    assert database.get_ride(ride_id)['total_elapsed_s'] == 5
    assert manager.sample_count == 1
    timers[0].cancel.assert_called_once_with()

    manager.record_heart_rate(160)
    assert len(database.get_heart_rate_samples(ride_id)) == 1

    manager.resume()
    assert manager.state == 'recording'
    manager._on_location({
            'latitude': 51.5001,
            'longitude': -0.12,
            'altitude': 19.0,
            'speed': 5.0,
            'accuracy': 3.0,
            'timestamp': '2026-10-18T19:20:02+00:00',
        })
    manager.record_heart_rate(145, timestamp='2026-10-18T19:20:03+00:00')
    manager.stop()

    ride = database.get_ride(ride_id)
    assert manager.state == 'finished'
    assert ride['status'] == 'completed'
    assert ride['total_elapsed_s'] == 8
    assert ride['total_distance_m'] > 0
    assert database.get_sample_count(ride_id) == 2
    assert len(database.get_heart_rate_samples(ride_id)) == 2
    assert manager.sample_count == 2
    assert len(timers) == 2
    for timer in timers:
        timer.cancel.assert_called_once_with()


def test_discard_removes_ride_and_clears_metrics(ride_manager, database):
    manager, timers = ride_manager
    manager.start()
    ride_id = manager.ride_id
    manager._on_location({
        'latitude': 51.5,
        'longitude': -0.12,
        'altitude': 18.0,
        'speed': 4.0,
        'accuracy': 3.0,
    })

    manager.discard()

    assert manager.state == 'idle'
    assert manager.ride_id == 0
    assert manager.sample_count == 0
    assert database.get_ride(ride_id) is None
    assert database.get_samples(ride_id) == []
    timers[0].cancel.assert_called_once_with()


def test_flush_progress_persists_current_elapsed_time(
    ride_manager, database, monkeypatch
):
    manager, _timers = ride_manager
    monkeypatch.setattr(
        ride_manager_module.time, 'monotonic', Mock(side_effect=[100, 108])
    )
    manager.start()
    manager.flush_progress()

    ride = database.get_ride(manager.ride_id)
    assert ride['total_elapsed_s'] == 8


def test_flush_progress_does_not_overwrite_android_service_progress(
    ride_manager, database, monkeypatch
):
    manager, _timers = ride_manager
    manager.start()
    ride_id = manager.ride_id
    database.update_ride_elapsed(ride_id, 12)
    monkeypatch.setattr(ride_manager_module, 'platform', 'android')

    manager.flush_progress()

    assert database.get_ride(ride_id)['total_elapsed_s'] == 12


def test_android_sync_updates_elapsed_time_from_monotonic_clock(
    ride_manager, monkeypatch
):
    manager, _timers = ride_manager
    monkeypatch.setattr(ride_manager_module, 'platform', 'android')
    monkeypatch.setattr(
        ride_manager_module.time, 'monotonic', Mock(side_effect=[100, 103])
    )
    monkeypatch.setattr(
        manager.service, 'start',
        lambda: setattr(manager.service, 'running', True),
    )

    manager.start()
    manager._sync_android_service(1)

    assert manager.elapsed_seconds == 3
    assert manager.elapsed_text == '00:00:03'


def test_close_releases_ui_resources_without_finishing_ride(
    ride_manager, database, monkeypatch
):
    manager, timers = ride_manager
    manager.start()
    ride_id = manager.ride_id
    manager.service.running = True
    stop_service = Mock()
    monkeypatch.setattr(ride_manager_module, 'platform', 'android')
    monkeypatch.setattr(manager.service, 'stop', stop_service)

    manager.close()

    assert database._conn is None
    assert manager.state == 'recording'
    timers[0].cancel.assert_called_once_with()
    manager.location.stop.assert_called_once_with()
    stop_service.assert_not_called()
    assert manager.service.running
    database.open()
    assert database.get_ride(ride_id)['status'] == 'active'
