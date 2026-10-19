"""Ride lifecycle, metric calculation, and durable sample recording."""

import math
import time

from kivy.clock import Clock
from kivy.event import EventDispatcher
from kivy.logger import Logger
from kivy.properties import BooleanProperty, NumericProperty, StringProperty
from kivy.utils import platform

from cycling_tracker.location import LocationProvider, haversine
from cycling_tracker.models.database import Database
from cycling_tracker.services.controller import RecordingServiceController


class RideManager(EventDispatcher):
    """Manage one active ride and expose live values to Kivy."""

    state = StringProperty('idle')
    ride_id = NumericProperty(0)
    elapsed_seconds = NumericProperty(0)
    speed_kmh = NumericProperty(0.0)
    altitude_m = NumericProperty(0.0)
    distance_km = NumericProperty(0.0)
    heart_rate_bpm = NumericProperty(0)
    sample_count = NumericProperty(0)
    elapsed_text = StringProperty('00:00:00')
    speed_text = StringProperty('\u2014')
    altitude_text = StringProperty('\u2014')
    distance_text = StringProperty('0.00')
    hr_text = StringProperty('\u2014')
    service_running = BooleanProperty(False)

    def __init__(self, db=None, **kwargs):
        super().__init__(**kwargs)
        self.db = db or Database()
        self.location = LocationProvider()
        self.service = RecordingServiceController()
        self._total_distance_m = 0.0
        self._last_lat = None
        self._last_lon = None
        self._timer_event = None
        self._started_monotonic = None
        self._elapsed_before_segment = 0

        self.bind(elapsed_seconds=self._update_elapsed_text)
        self.bind(speed_kmh=self._update_speed_text)
        self.bind(altitude_m=self._update_altitude_text)
        self.bind(distance_km=self._update_distance_text)
        self.bind(heart_rate_bpm=self._update_hr_text)

    def start(self):
        """Start a new ride or recover the last interrupted ride."""
        if self.state not in ('idle', 'finished'):
            Logger.warning(f'RideManager: cannot start from {self.state}')
            return False
        if self.db._conn is None:
            self.db.open()

        active = self.db.get_active_ride()
        if active:
            self.ride_id = active['id']
            self._total_distance_m = active['total_distance_m'] or 0.0
            self._elapsed_before_segment = active['total_elapsed_s'] or 0
            self.elapsed_seconds = self._elapsed_before_segment
            last = self.db.get_last_sample(self.ride_id)
            if last:
                self._last_lat = last['latitude']
                self._last_lon = last['longitude']
            self.sample_count = self.db.get_sample_count(self.ride_id)
            Logger.info(f'RideManager: recovering active ride {self.ride_id}')
        else:
            self._clear_metrics()
            self.ride_id = self.db.create_ride()

        self._started_monotonic = time.monotonic()
        self.distance_km = self._total_distance_m / 1000
        self.state = 'recording'
        try:
            if platform == 'android':
                self.service.start()
                self.service_running = True
                self._timer_event = Clock.schedule_interval(
                    self._sync_android_service, 1.0
                )
            else:
                self.location.start(self._on_location)
                self._timer_event = Clock.schedule_interval(self._tick, 1.0)
        except Exception:
            self.state = 'idle'
            self.service_running = self.service.running
            raise
        Logger.info(f'RideManager: ride {self.ride_id} recording')
        return True

    def pause(self):
        if self.state != 'recording':
            return
        self._capture_elapsed()
        self._elapsed_before_segment = self.elapsed_seconds
        self.state = 'paused'
        self._cancel_timer()
        if platform != 'android':
            self.location.stop()
        self._persist_progress()
        if platform == 'android':
            try:
                self.service.stop()
            finally:
                self.service_running = self.service.running

    def resume(self):
        if self.state != 'paused':
            return
        self._started_monotonic = time.monotonic()
        self.state = 'recording'
        try:
            if platform == 'android':
                self.service.start()
                self.service_running = True
                self._timer_event = Clock.schedule_interval(
                    self._sync_android_service, 1.0
                )
            else:
                self.location.start(self._on_location)
                self._timer_event = Clock.schedule_interval(self._tick, 1.0)
        except Exception:
            self.state = 'paused'
            self._started_monotonic = None
            self.service_running = self.service.running
            raise

    def stop(self):
        if self.state not in ('recording', 'paused'):
            return
        if self.state == 'recording':
            self._capture_elapsed()
        self._cancel_timer()
        self.location.stop()
        self._persist_progress()
        self.db.finish_ride(
            self.ride_id,
            self._total_distance_m,
            self.elapsed_seconds
        )
        try:
            if self.service.running:
                self.service.stop()
        finally:
            self.service_running = self.service.running
            self.state = 'finished'
        Logger.info(f'RideManager: ride {self.ride_id} finished')

    def discard(self):
        if self.state in ('idle', 'finished'):
            return
        self._cancel_timer()
        self.location.stop()
        if self.service.running:
            self.service.stop()
        self.service_running = False
        self.db.discard_ride(self.ride_id)
        self._clear_metrics()
        self.state = 'idle'

    def reset(self):
        self._clear_metrics()
        self.state = 'idle'

    def flush_progress(self):
        """Persist elapsed ride progress before the UI is suspended."""
        if self.state != 'recording' or platform == 'android':
            return
        self._capture_elapsed()
        self._persist_progress()

    def close(self):
        """Release UI-process resources without stopping an Android service."""
        self.flush_progress()
        self._cancel_timer()
        self.location.stop()
        self.db.close()

    def record_heart_rate(self, bpm, timestamp=None):
        """Persist a BLE measurement and update the live heart-rate value."""
        if self.state != 'recording':
            return
        self.db.insert_heart_rate(self.ride_id, bpm, timestamp=timestamp)
        self.heart_rate_bpm = int(bpm)

    def _on_location(self, loc):
        if self.state != 'recording':
            return
        lat = float(loc['latitude'])
        lon = float(loc['longitude'])
        if (
            not math.isfinite(lat)
            or not math.isfinite(lon)
            or not -90 <= lat <= 90
            or not -180 <= lon <= 180
        ):
            Logger.warning('RideManager: skipped invalid GPS coordinates')
            return
        accuracy = loc.get('accuracy')
        accuracy = float(accuracy) if accuracy is not None else None
        if accuracy is not None and (
            not math.isfinite(accuracy) or accuracy < 0 or accuracy > 50
        ):
            Logger.debug(f'RideManager: skipped inaccurate GPS fix ({accuracy}m)')
            return
        altitude = loc.get('altitude')
        altitude = float(altitude) if altitude is not None else None
        if altitude is not None and not math.isfinite(altitude):
            altitude = None
        speed = float(loc.get('speed') or 0.0)
        if not math.isfinite(speed) or speed < 0:
            speed = 0.0
        bearing = loc.get('bearing')
        bearing = float(bearing) if bearing is not None else None
        if bearing is not None and not math.isfinite(bearing):
            bearing = None
        if self._last_lat is not None and self._last_lon is not None:
            distance = haversine(self._last_lat, self._last_lon, lat, lon)
            if distance < 500:
                self._total_distance_m += distance
        self._last_lat, self._last_lon = lat, lon

        self.db.insert_sample(
            self.ride_id,
            latitude=lat,
            longitude=lon,
            altitude=altitude,
            speed=speed,
            bearing=bearing,
            accuracy=accuracy,
            timestamp=loc.get('timestamp'),
        )
        self.sample_count += 1
        self.speed_kmh = speed * 3.6
        self.altitude_m = altitude or 0.0
        self.distance_km = self._total_distance_m / 1000
        self.db.update_ride_distance(self.ride_id, self._total_distance_m)

    def _sync_android_service(self, _dt):
        """Refresh live metrics from samples written by the Android service."""
        if self.state != 'recording':
            return
        ride = self.db.get_ride(self.ride_id)
        if ride is None or ride['status'] != 'active':
            return
        self.elapsed_seconds = max(
            self.elapsed_seconds, int(ride['total_elapsed_s'] or 0)
        )
        self._total_distance_m = float(ride['total_distance_m'] or 0.0)
        self.distance_km = self._total_distance_m / 1000
        self.sample_count = self.db.get_sample_count(self.ride_id)
        sample = self.db.get_last_sample(self.ride_id)
        if sample:
            self.speed_kmh = float(sample['speed'] or 0.0) * 3.6
            self.altitude_m = float(sample['altitude'] or 0.0)

    def _tick(self, _dt):
        self._capture_elapsed()
        if self.elapsed_seconds % 30 == 0:
            self._persist_progress()

    def _capture_elapsed(self):
        if self._started_monotonic is not None:
            self.elapsed_seconds = self._elapsed_before_segment + int(
                time.monotonic() - self._started_monotonic
            )

    def _persist_progress(self):
        self.db.update_ride_elapsed(self.ride_id, self.elapsed_seconds)
        self.db.update_ride_distance(self.ride_id, self._total_distance_m)
        self.db.conn.commit()

    def _cancel_timer(self):
        if self._timer_event is not None:
            self._timer_event.cancel()
            self._timer_event = None

    def _clear_metrics(self):
        self.elapsed_seconds = 0
        self.speed_kmh = 0.0
        self.altitude_m = 0.0
        self.distance_km = 0.0
        self.heart_rate_bpm = 0
        self.sample_count = 0
        self._total_distance_m = 0.0
        self._last_lat = None
        self._last_lon = None
        self._elapsed_before_segment = 0
        self._started_monotonic = None
        self.ride_id = 0

    def _update_elapsed_text(self, *_args):
        hours, remaining = divmod(self.elapsed_seconds, 3600)
        minutes, seconds = divmod(remaining, 60)
        self.elapsed_text = f'{hours:02d}:{minutes:02d}:{seconds:02d}'

    def _update_speed_text(self, *_args):
        self.speed_text = f'{self.speed_kmh:.1f}'

    def _update_altitude_text(self, *_args):
        self.altitude_text = f'{self.altitude_m:.0f}'

    def _update_distance_text(self, *_args):
        self.distance_text = f'{self.distance_km:.2f}'

    def _update_hr_text(self, *_args):
        self.hr_text = str(self.heart_rate_bpm) if self.heart_rate_bpm else '\u2014'
