"""
CyclingTracker — Main application entry point.

A Kivy Android cycling tracker that records GPS location,
speed, altitude, elapsed time, and BLE heart-rate data.
"""

import os
import sys

# Ensure the app package is importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from kivy.config import Config
# Disable multitouch emulation (red dots) on desktop
Config.set('input', 'mouse', 'mouse,multitouch_on_demand')

from kivy.app import App
from kivy.clock import Clock
from kivy.logger import Logger
from kivy.properties import StringProperty, BooleanProperty, ObjectProperty
from kivy.uix.screenmanager import ScreenManager
from kivy.utils import platform

from cycling_tracker.screens.dashboard import DashboardScreen
from cycling_tracker.screens.ride import RideScreen
from cycling_tracker.screens.history import HistoryScreen
from cycling_tracker.screens.settings import SettingsScreen
from cycling_tracker.permissions import PermissionManager
from cycling_tracker.ride_manager import RideManager
from cycling_tracker.ble.hr_monitor import HeartRateMonitor


class CyclingTrackerApp(App):
    """Root application for the Cycling Tracker."""

    # Observable permission states
    location_permission = BooleanProperty(False)
    ble_permission = BooleanProperty(False)
    bg_location_permission = BooleanProperty(False)
    notification_permission = BooleanProperty(False)

    # Sensor / service status strings
    gps_status = StringProperty('Unknown')
    ble_status = StringProperty('Disconnected')
    service_status = StringProperty('Stopped')

    # Permission manager instance
    permission_manager = ObjectProperty(None, allownone=True)
    ride_manager = ObjectProperty(None, allownone=True)
    heart_rate_monitor = ObjectProperty(None, allownone=True)

    def build(self):
        """Build the root widget tree."""
        self.title = 'CyclingTracker'
        self.ride_manager = RideManager()
        self.ride_manager.bind(
            service_running=self._on_service_state,
            state=self._on_ride_state,
        )
        self.heart_rate_monitor = HeartRateMonitor(
            on_heart_rate=self._on_heart_rate,
            on_status=self._on_ble_status,
            on_devices=self._on_ble_devices,
        )
        self.sm = ScreenManager()
        self.sm.add_widget(DashboardScreen(name='dashboard'))
        self.sm.add_widget(RideScreen(name='ride'))
        self.sm.add_widget(HistoryScreen(name='history'))
        self.sm.add_widget(SettingsScreen(name='settings'))
        return self.sm

    def on_start(self):
        """Called after build(); initialize platform services."""
        Logger.info('CyclingTracker: on_start')
        self.permission_manager = PermissionManager(self)
        Clock.schedule_once(self._deferred_init, 0.5)

    def _deferred_init(self, dt):
        """Request permissions after the UI is fully rendered."""
        Logger.info('CyclingTracker: deferred init — requesting permissions')
        self.permission_manager.request_all()
        self.permission_manager.refresh_status()

    def _on_service_state(self, _instance, running):
        if not running:
            self.service_status = 'Stopped'
        elif platform == 'android':
            self.service_status = 'Recording in foreground service'
        else:
            self.service_status = 'Recording (desktop)'

    def _on_ride_state(self, _instance, state):
        if state == 'recording' and self.heart_rate_monitor is not None:
            self.heart_rate_monitor.disconnect()
        if state != 'recording' and self.service_status != 'Stopped':
            self.service_status = 'Stopped'

    def _on_heart_rate(self, bpm, timestamp):
        if self.ride_manager is not None:
            self.ride_manager.record_heart_rate(bpm, timestamp)

    def _on_ble_status(self, status):
        self.ble_status = status
        if self.sm.has_screen('settings'):
            self.sm.get_screen('settings').status_text = status

    def _on_ble_devices(self, devices):
        if self.sm.has_screen('settings'):
            self.sm.get_screen('settings').show_devices(devices)

    def on_pause(self):
        """Allow the app to pause (Android lifecycle)."""
        Logger.info('CyclingTracker: on_pause')
        if self.heart_rate_monitor is not None:
            self.heart_rate_monitor.stop_scan()
        if self.ride_manager is not None:
            self.ride_manager.flush_progress()
        return True

    def on_resume(self):
        """Refresh permission state when returning from background."""
        Logger.info('CyclingTracker: on_resume')
        if self.permission_manager:
            self.permission_manager.refresh_status()

    def on_stop(self):
        """Release resources owned by the UI process."""
        Logger.info('CyclingTracker: on_stop')
        if self.heart_rate_monitor is not None:
            self.heart_rate_monitor.disconnect()
        if self.ride_manager is not None:
            self.ride_manager.close()

    def switch_screen(self, screen_name):
        """Navigate to the named screen."""
        if self.sm.has_screen(screen_name):
            self.sm.current = screen_name
        else:
            Logger.warning(f'CyclingTracker: no screen named {screen_name}')


def main():
    CyclingTrackerApp().run()


if __name__ == '__main__':
    main()
