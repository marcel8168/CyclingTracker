"""Shared pytest fixtures for host-side tests."""

from unittest.mock import Mock

import pytest

from cycling_tracker.models.database import Database
from cycling_tracker.ride_manager import RideManager


@pytest.fixture
def database(tmp_path):
    db = Database(str(tmp_path / 'rides.db'))
    db.open()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def ride_manager(database, monkeypatch):
    import cycling_tracker.ride_manager as ride_manager_module

    monkeypatch.setattr(ride_manager_module, 'platform', 'linux')

    timers = []

    def schedule_interval(*_args):
        timer = Mock()
        timers.append(timer)
        return timer

    monkeypatch.setattr(
        ride_manager_module.Clock, 'schedule_interval', schedule_interval
    )
    manager = RideManager(db=database)
    monkeypatch.setattr(manager.location, 'start', Mock())
    monkeypatch.setattr(manager.location, 'stop', Mock())
    return manager, timers
