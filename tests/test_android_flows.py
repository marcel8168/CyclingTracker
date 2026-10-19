"""Host-side tests for Android service and permission orchestration."""

import sys
import types
from types import SimpleNamespace
from unittest import mock

import pytest

from cycling_tracker.permissions import PermissionManager
from cycling_tracker.services.controller import RecordingServiceController


def test_android_start_and_stop_are_idempotent(monkeypatch):
    activity = object()
    service = SimpleNamespace(start=mock.Mock(), stop=mock.Mock())
    classes = {
        'org.kivy.android.PythonActivity':
            SimpleNamespace(mActivity=activity),
        'org.cyclingtracker.cyclingtracker.ServiceRide': service,
    }
    jnius = types.ModuleType('jnius')
    jnius.autoclass = lambda name: classes[name]

    monkeypatch.setattr(
        'cycling_tracker.services.controller.platform', 'android'
    )
    monkeypatch.setitem(sys.modules, 'jnius', jnius)
    controller = RecordingServiceController()
    controller.start()
    controller.start()
    controller.stop()
    controller.stop()

    service.start.assert_called_once_with(activity, '')
    service.stop.assert_called_once_with(activity)
    assert not controller.running
    assert controller._service is None
    assert controller._activity is None


def test_android_start_requires_activity(monkeypatch):
    jnius = types.ModuleType('jnius')
    jnius.autoclass = lambda _name: SimpleNamespace(mActivity=None)

    monkeypatch.setattr(
        'cycling_tracker.services.controller.platform', 'android'
    )
    monkeypatch.setitem(sys.modules, 'jnius', jnius)
    controller = RecordingServiceController()
    with pytest.raises(
        RuntimeError, match='Android activity is unavailable'
    ):
        controller.start()

    assert not controller.running


def _android_modules(api_level, granted):
    build_version = SimpleNamespace(SDK_INT=api_level)
    jnius = types.ModuleType('jnius')
    jnius.autoclass = lambda _name: build_version

    requested = []
    permissions = types.ModuleType('android.permissions')
    permissions.request_permissions = lambda perms, callback: requested.append(
        (perms, callback)
    )
    permissions.check_permission = lambda permission: granted.get(
        permission, False
    )

    android = types.ModuleType('android')
    android.__path__ = []
    return android, permissions, jnius, requested


def test_android_13_requests_runtime_permissions_and_refreshes_status(
    monkeypatch,
):
    granted = {
        'android.permission.ACCESS_FINE_LOCATION': True,
        'android.permission.BLUETOOTH_SCAN': True,
        'android.permission.BLUETOOTH_CONNECT': True,
        'android.permission.POST_NOTIFICATIONS': True,
    }
    android, permissions, jnius, requested = _android_modules(
        33, granted
    )
    app = SimpleNamespace(
        location_permission=False,
        ble_permission=False,
        bg_location_permission=False,
        notification_permission=False,
        gps_status='',
        ble_status='Disconnected',
    )

    monkeypatch.setattr(
        'cycling_tracker.permissions.platform', 'android'
    )
    monkeypatch.setitem(sys.modules, 'android', android)
    monkeypatch.setitem(sys.modules, 'android.permissions', permissions)
    monkeypatch.setitem(sys.modules, 'jnius', jnius)
    manager = PermissionManager(app)
    manager.request_all()
    perms, callback = requested[0]
    callback(perms, [True] * len(perms))

    assert len(requested) == 1
    assert 'android.permission.BLUETOOTH_SCAN' in perms
    assert 'android.permission.BLUETOOTH_CONNECT' in perms
    assert 'android.permission.POST_NOTIFICATIONS' in perms
    assert manager.can_record
    assert manager.can_use_ble
    assert not manager.can_record_background
    assert app.notification_permission


def test_android_10_requests_background_location_after_foreground_grant(
    monkeypatch,
):
    granted = {'android.permission.ACCESS_FINE_LOCATION': True}
    android, permissions, jnius, requested = _android_modules(
        29, granted
    )
    app = SimpleNamespace(
        location_permission=False,
        ble_permission=False,
        bg_location_permission=False,
        notification_permission=False,
        gps_status='',
        ble_status='Disconnected',
    )

    monkeypatch.setattr(
        'cycling_tracker.permissions.platform', 'android'
    )
    monkeypatch.setitem(sys.modules, 'android', android)
    monkeypatch.setitem(sys.modules, 'android.permissions', permissions)
    monkeypatch.setitem(sys.modules, 'jnius', jnius)
    manager = PermissionManager(app)
    manager.request_all()
    foreground_permissions, callback = requested[0]
    callback(foreground_permissions, [True] * len(foreground_permissions))

    assert len(requested) == 2
    assert requested[1][0] == manager.BG_LOCATION_PERMS
    assert manager.can_record
    assert not manager.can_record_background
