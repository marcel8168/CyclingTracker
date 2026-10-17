"""
Ride screen — displays live ride metrics and controls recording.

Metrics: elapsed time, speed, altitude, distance, heart rate.
Controls: start/pause/resume/stop ride.
"""

from kivy.app import App
from kivy.logger import Logger
from kivy.properties import StringProperty, BooleanProperty, ObjectProperty
from kivy.uix.screenmanager import Screen

class RideScreen(Screen):
    """Live ride recording screen."""

    # Display properties bound in KV
    elapsed_text = StringProperty('00:00:00')
    speed_text = StringProperty('\u2014')
    altitude_text = StringProperty('\u2014')
    distance_text = StringProperty('0.00')
    hr_text = StringProperty('\u2014')

    ride_button_text = StringProperty('Start')
    stop_button_visible = BooleanProperty(False)

    ride_manager = ObjectProperty(None, allownone=True)

    def on_enter(self):
        Logger.info('RideScreen: on_enter')
        if self.ride_manager is None:
            self.ride_manager = App.get_running_app().ride_manager
            # Bind manager properties to screen properties
            self.ride_manager.bind(elapsed_text=self.setter('elapsed_text'))
            self.ride_manager.bind(speed_text=self.setter('speed_text'))
            self.ride_manager.bind(altitude_text=self.setter('altitude_text'))
            self.ride_manager.bind(distance_text=self.setter('distance_text'))
            self.ride_manager.bind(hr_text=self.setter('hr_text'))
            self.ride_manager.bind(state=self._on_state_change)

    def _on_state_change(self, instance, state):
        """Update button text based on ride state."""
        if state == 'idle':
            self.ride_button_text = 'Start'
            self.stop_button_visible = False
        elif state == 'recording':
            self.ride_button_text = 'Pause'
            self.stop_button_visible = True
        elif state == 'paused':
            self.ride_button_text = 'Resume'
            self.stop_button_visible = True
        elif state == 'finished':
            self.ride_button_text = 'New Ride'
            self.stop_button_visible = False

    def toggle_ride(self):
        """Primary button action: start / pause / resume."""
        app = App.get_running_app()
        rm = self.ride_manager

        if rm.state == 'idle' or rm.state == 'finished':
            # Check permissions before starting
            if app.permission_manager and not app.permission_manager.can_record:
                Logger.warning('RideScreen: cannot start — location permission missing')
                self.ride_button_text = 'Location permission required'
                return
            if rm.state == 'finished':
                rm.reset()
            try:
                rm.start()
            except Exception as exc:
                Logger.exception(f'RideScreen: could not start ride: {exc}')
                self.ride_button_text = f'Could not start: {exc}'
                return

        elif rm.state == 'recording':
            rm.pause()

        elif rm.state == 'paused':
            rm.resume()

    def stop_ride(self):
        """Stop and finish the current ride."""
        if self.ride_manager:
            self.ride_manager.stop()

    def discard_ride(self):
        """Discard the current ride without saving."""
        if self.ride_manager:
            self.ride_manager.discard()
