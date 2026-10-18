"""Host-side tests for Android service and permission orchestration."""

import sys
import types
import unittest
from types import SimpleNamespace
from unittest import mock

from cycling_tracker.permissions import PermissionManager
from cycling_tracker.services.controller import RecordingServiceController


class RecordingServiceControllerTests(unittest.TestCase):
    def test_android_start_and_stop_are_idempotent(self):
        activity = object()
        service = SimpleNamespace(start=mock.Mock(), stop=mock.Mock())
        classes = {
            'org.kivy.android.PythonActivity':
                SimpleNamespace(mActivity=activity),
            'org.cyclingtracker.cyclingtracker.ServiceRide': service,
        }
        jnius = types.ModuleType('jnius')
        jnius.autoclass = lambda name: classes[name]

        with (
            mock.patch('cycling_tracker.services.controller.platform', 'android'),
            mock.patch.dict(sys.modules, {'jnius': jnius}),
        ):
            controller = RecordingServiceController()
            controller.start()
            controller.start()
            controller.stop()
            controller.stop()

        service.start.assert_called_once_with(activity, '')
        service.stop.assert_called_once_with(activity)
        self.assertFalse(controller.running)
        self.assertIsNone(controller._service)
        self.assertIsNone(controller._activity)

    def test_android_start_requires_activity(self):
        jnius = types.ModuleType('jnius')
        jnius.autoclass = lambda _name: SimpleNamespace(mActivity=None)

        with (
            mock.patch('cycling_tracker.services.controller.platform', 'android'),
            mock.patch.dict(sys.modules, {'jnius': jnius}),
        ):
            controller = RecordingServiceController()
            with self.assertRaisesRegex(
                RuntimeError, 'Android activity is unavailable'
            ):
                controller.start()

        self.assertFalse(controller.running)


class PermissionManagerTests(unittest.TestCase):
    @staticmethod
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

    def test_android_13_requests_runtime_permissions_and_refreshes_status(self):
        granted = {
            'android.permission.ACCESS_FINE_LOCATION': True,
            'android.permission.BLUETOOTH_SCAN': True,
            'android.permission.BLUETOOTH_CONNECT': True,
            'android.permission.POST_NOTIFICATIONS': True,
        }
        android, permissions, jnius, requested = self._android_modules(
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

        with (
            mock.patch('cycling_tracker.permissions.platform', 'android'),
            mock.patch.dict(
                sys.modules,
                {
                    'android': android,
                    'android.permissions': permissions,
                    'jnius': jnius,
                },
            ),
        ):
            manager = PermissionManager(app)
            manager.request_all()
            perms, callback = requested[0]
            callback(perms, [True] * len(perms))

        self.assertEqual(len(requested), 1)
        self.assertIn('android.permission.BLUETOOTH_SCAN', perms)
        self.assertIn('android.permission.BLUETOOTH_CONNECT', perms)
        self.assertIn('android.permission.POST_NOTIFICATIONS', perms)
        self.assertTrue(manager.can_record)
        self.assertTrue(manager.can_use_ble)
        self.assertFalse(manager.can_record_background)
        self.assertTrue(app.notification_permission)

    def test_android_10_requests_background_location_after_foreground_grant(self):
        granted = {'android.permission.ACCESS_FINE_LOCATION': True}
        android, permissions, jnius, requested = self._android_modules(
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

        with (
            mock.patch('cycling_tracker.permissions.platform', 'android'),
            mock.patch.dict(
                sys.modules,
                {
                    'android': android,
                    'android.permissions': permissions,
                    'jnius': jnius,
                },
            ),
        ):
            manager = PermissionManager(app)
            manager.request_all()
            foreground_permissions, callback = requested[0]
            callback(foreground_permissions, [True] * len(foreground_permissions))

        self.assertEqual(len(requested), 2)
        self.assertEqual(requested[1][0], manager.BG_LOCATION_PERMS)
        self.assertTrue(manager.can_record)
        self.assertFalse(manager.can_record_background)


if __name__ == '__main__':
    unittest.main()
