"""Tests for foreground ride-service sensor persistence."""

import pytest

from cycling_tracker.services.ride_service import (
    _LocationListener,
    _record_heart_rate,
    _subscribe_to_location,
)


def test_records_queued_heart_rate_measurement(database):
    ride_id = database.create_ride()
    timestamp = '2026-10-18T19:20:00+00:00'

    _record_heart_rate(database, ride_id, (143, timestamp))

    samples = database.get_heart_rate_samples(ride_id)
    assert len(samples) == 1
    assert samples[0]['heart_rate'] == 143
    assert samples[0]['timestamp'] == timestamp


def test_location_updates_use_main_looper_for_enabled_providers():
    class FakeLocationManager:
        GPS_PROVIDER = 'gps'
        NETWORK_PROVIDER = 'network'

    main_looper = object()
    looper = type('FakeLooper', (), {
        'getMainLooper': staticmethod(lambda: main_looper),
    })
    requests = []
    manager = type('FakeManager', (), {
        'isProviderEnabled': staticmethod(lambda provider: provider == 'gps'),
        'requestLocationUpdates': staticmethod(
            lambda *args: requests.append(args)
        ),
    })()
    listener = object()

    providers = _subscribe_to_location(
        manager, FakeLocationManager, listener, looper
    )

    assert providers == ['gps']
    assert requests == [('gps', 1000, 2.0, listener, main_looper)]


def test_location_listener_bridge_forwards_location_to_python_callback():
    received = []

    class FakeJavaClass:
        pass

    class FakeBridge:
        def __init__(self, callback):
            self.callback = callback

    def fake_java_method(_signature):
        return lambda method: method

    def fake_autoclass(name):
        assert name.endswith('CyclingTrackerLocationListener')
        return FakeBridge

    listener, callback = _LocationListener(
        received.append, FakeJavaClass, fake_java_method, fake_autoclass
    )
    location = object()

    listener.callback.onLocation(location)

    assert received == [location]
    assert callback is listener.callback


def test_location_updates_report_when_all_providers_are_disabled():
    class FakeLocationManager:
        GPS_PROVIDER = 'gps'
        NETWORK_PROVIDER = 'network'

    looper = type('FakeLooper', (), {
        'getMainLooper': staticmethod(lambda: object()),
    })
    manager = type('FakeManager', (), {
        'isProviderEnabled': staticmethod(lambda _provider: False),
    })()

    with pytest.raises(
        RuntimeError, match='No enabled Android location providers'
    ):
        _subscribe_to_location(manager, FakeLocationManager, object(), looper)
