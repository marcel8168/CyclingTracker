"""Lifecycle controller for the Android ride-recording service."""

from kivy.logger import Logger
from kivy.utils import platform


class RecordingServiceController:
    """Start and stop the foreground service used while recording."""

    def __init__(self):
        self._service = None
        self._activity = None
        self.running = False

    def start(self):
        if platform != 'android':
            self.running = True
            return
        if self.running:
            return

        from jnius import autoclass

        PythonActivity = autoclass('org.kivy.android.PythonActivity')
        self._activity = PythonActivity.mActivity
        if self._activity is None:
            raise RuntimeError('Android activity is unavailable')
        self._service = autoclass(
            'org.cyclingtracker.cyclingtracker.ServiceRide'
        )
        self._service.start(self._activity, '')
        self.running = True
        Logger.info('RecordingService: foreground service started')

    def stop(self):
        if not self.running:
            return
        if platform == 'android' and self._service is not None:
            self._service.stop(self._activity)
        self._service = None
        self._activity = None
        self.running = False
        Logger.info('RecordingService: foreground service stopped')
