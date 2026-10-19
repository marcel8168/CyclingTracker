"""
Permission management for CyclingTracker.

Handles requesting and tracking Android runtime permissions.
On non-Android platforms, all permissions are reported as granted
to allow desktop development and testing.
"""

from kivy.clock import Clock
from kivy.logger import Logger
from kivy.utils import platform

# Android SDK version constants
ANDROID_10 = 29  # ACCESS_BACKGROUND_LOCATION split out
ANDROID_12 = 31  # BLUETOOTH_SCAN / BLUETOOTH_CONNECT
ANDROID_13 = 33  # POST_NOTIFICATIONS


class PermissionManager:
    """Manages Android runtime permission requests and status tracking."""

    # Permissions grouped by feature
    LOCATION_PERMS = [
        'android.permission.ACCESS_FINE_LOCATION',
        'android.permission.ACCESS_COARSE_LOCATION',
    ]
    BG_LOCATION_PERMS = [
        'android.permission.ACCESS_BACKGROUND_LOCATION',
    ]
    BLE_PERMS_LEGACY = [
        'android.permission.BLUETOOTH',
        'android.permission.BLUETOOTH_ADMIN',
    ]
    BLE_PERMS_MODERN = [
        'android.permission.BLUETOOTH_SCAN',
        'android.permission.BLUETOOTH_CONNECT',
    ]
    NOTIFICATION_PERMS = [
        'android.permission.POST_NOTIFICATIONS',
    ]

    def __init__(self, app):
        self.app = app
        self._sdk_version = self._get_sdk_version()
        Logger.info(f'PermissionManager: SDK version = {self._sdk_version}')

    @staticmethod
    def _get_sdk_version():
        """Return the Android SDK version, or 0 on non-Android."""
        if platform != 'android':
            return 0
        try:
            from jnius import autoclass
            Build = autoclass('android.os.Build$VERSION')
            return Build.SDK_INT
        except Exception:
            Logger.warning('PermissionManager: could not read SDK_INT')
            return 0

    def _build_permission_list(self):
        """Return the list of permissions to request for this device."""
        perms = list(self.LOCATION_PERMS)

        if self._sdk_version >= ANDROID_12:
            perms.extend(self.BLE_PERMS_MODERN)
        else:
            perms.extend(self.BLE_PERMS_LEGACY)

        if self._sdk_version >= ANDROID_13:
            perms.extend(self.NOTIFICATION_PERMS)

        return perms

    def request_all(self):
        """Request all required permissions.

        Background location must be requested separately after
        foreground location is granted (Android 10+ requirement).
        """
        if platform != 'android':
            Logger.info('PermissionManager: non-Android — granting all')
            self._set_all_granted()
            return

        perms = self._build_permission_list()
        Logger.info(f'PermissionManager: requesting {perms}')

        try:
            from android.permissions import request_permissions
            request_permissions(perms, self._on_permissions_result)
        except ImportError as exc:
            Logger.error(
                f'PermissionManager: Android permission API unavailable: {exc}'
            )
            self._set_unavailable()

    def _on_permissions_result(self, permissions, grant_results):
        """Callback after the user responds to the permission dialog."""
        Clock.schedule_once(
            lambda _dt: self._handle_permissions_result(
                permissions, grant_results
            ),
            0,
        )

    def _handle_permissions_result(self, permissions, grant_results):
        """Apply permission results on Kivy's main thread."""
        Logger.info(f'PermissionManager: result — {list(zip(permissions, grant_results))}')
        self.refresh_status()

        # If foreground location was just granted, request background location
        if self.app.location_permission and not self.app.bg_location_permission:
            if self._sdk_version >= ANDROID_10:
                self._request_background_location()

    def _request_background_location(self):
        """Request ACCESS_BACKGROUND_LOCATION separately (Android 10+)."""
        if self._sdk_version >= 30:
            Logger.info(
                'PermissionManager: Android 11+ requires background location '
                'to be enabled from app settings'
            )
            return
        Logger.info('PermissionManager: requesting background location')
        try:
            from android.permissions import request_permissions
            request_permissions(
                self.BG_LOCATION_PERMS,
                self._on_bg_location_result
            )
        except ImportError as exc:
            Logger.error(
                f'PermissionManager: background permission API unavailable: {exc}'
            )
            self._set_unavailable()

    @staticmethod
    def open_app_settings():
        """Open Android app details so the user can enable background access."""
        if platform != 'android':
            return
        from jnius import autoclass

        PythonActivity = autoclass('org.kivy.android.PythonActivity')
        activity = PythonActivity.mActivity
        if activity is None:
            raise RuntimeError('Android activity is unavailable')
        Settings = autoclass('android.provider.Settings')
        Intent = autoclass('android.content.Intent')
        Uri = autoclass('android.net.Uri')
        intent = Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS)
        intent.setData(Uri.parse(f'package:{activity.getPackageName()}'))
        activity.startActivity(intent)

    def _on_bg_location_result(self, permissions, grant_results):
        """Callback for background-location permission."""
        Clock.schedule_once(
            lambda _dt: self._handle_bg_location_result(
                permissions, grant_results
            ),
            0,
        )

    def _handle_bg_location_result(self, permissions, grant_results):
        """Apply background-location results on Kivy's main thread."""
        Logger.info(f'PermissionManager: bg location result — {list(zip(permissions, grant_results))}')
        self.refresh_status()

    def refresh_status(self):
        """Re-check which permissions are currently granted and update app properties."""
        if platform != 'android':
            self._set_all_granted()
            return

        try:
            from android.permissions import check_permission
        except ImportError as exc:
            Logger.error(
                f'PermissionManager: permission checker unavailable: {exc}'
            )
            self._set_unavailable()
            return

        loc = check_permission(self.LOCATION_PERMS[0])
        self.app.location_permission = loc
        self.app.gps_status = 'Available' if loc else 'No permission'

        if self._sdk_version >= ANDROID_12:
            ble = all(check_permission(p) for p in self.BLE_PERMS_MODERN)
        else:
            ble = True  # legacy perms are install-time
        self.app.ble_permission = ble
        if not ble and self.app.ble_status == 'Disconnected':
            self.app.ble_status = 'Permission required'

        bg = False
        if self._sdk_version >= ANDROID_10:
            bg = all(check_permission(p) for p in self.BG_LOCATION_PERMS)
        else:
            bg = loc  # pre-10, foreground location covers background
        self.app.bg_location_permission = bg

        notif = True
        if self._sdk_version >= ANDROID_13:
            notif = all(check_permission(p) for p in self.NOTIFICATION_PERMS)
        self.app.notification_permission = notif

        Logger.info(
            f'PermissionManager: loc={loc} ble={ble} bg={bg} notif={notif}'
        )

    def _set_all_granted(self):
        """Set all permissions as granted (for desktop/testing)."""
        self.app.location_permission = True
        self.app.ble_permission = True
        self.app.bg_location_permission = True
        self.app.notification_permission = True
        self.app.gps_status = 'Available (desktop)'

    def _set_unavailable(self):
        self.app.location_permission = False
        self.app.ble_permission = False
        self.app.bg_location_permission = False
        self.app.notification_permission = False
        self.app.gps_status = 'Permission API unavailable'
        self.app.ble_status = 'Permission API unavailable'

    @property
    def can_record(self):
        """Whether minimum permissions for ride recording are met."""
        return self.app.location_permission

    @property
    def can_use_ble(self):
        """Whether BLE scanning/connection permissions are met."""
        return self.app.ble_permission

    @property
    def can_record_background(self):
        """Whether background recording is permitted."""
        return self.app.location_permission and self.app.bg_location_permission
