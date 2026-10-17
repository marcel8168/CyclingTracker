"""
GPS location provider for CyclingTracker.

Uses plyer.gps on Android for real GPS data.
On desktop, provides a simulated location feed for UI development.
"""

import time
import math
import random
from datetime import datetime, timezone

from kivy.clock import Clock
from kivy.event import EventDispatcher
from kivy.logger import Logger
from kivy.properties import (
    NumericProperty, BooleanProperty, StringProperty
)
from kivy.utils import platform


class LocationProvider(EventDispatcher):
    """Abstraction over platform GPS.

    Fires callbacks with location dicts containing:
        latitude, longitude, altitude, speed, bearing, accuracy

    Properties are observable for KV binding.
    """

    latitude = NumericProperty(0.0)
    longitude = NumericProperty(0.0)
    altitude = NumericProperty(0.0)
    speed = NumericProperty(0.0)       # m/s
    bearing = NumericProperty(0.0)
    accuracy = NumericProperty(0.0)    # metres
    status = StringProperty('stopped')
    active = BooleanProperty(False)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._gps = None
        self._callback = None
        self._sim_event = None
        # Simulation state (desktop only)
        self._sim_lat = 51.0504    # Cologne, Germany
        self._sim_lon = 6.8820
        self._sim_heading = 45.0   # degrees

    def start(self, callback, min_time_ms=1000, min_distance_m=2):
        """Start receiving location updates.

        Args:
            callback: Called with (location_dict) on each fix.
            min_time_ms: Minimum interval between updates (ms).
            min_distance_m: Minimum distance change to trigger update (m).
        """
        self._callback = callback

        if platform == 'android':
            self._start_android(min_time_ms, min_distance_m)
        else:
            self._start_simulation(min_time_ms)

    def stop(self):
        """Stop receiving location updates."""
        if platform == 'android':
            self._stop_android()
        else:
            self._stop_simulation()
        self.active = False
        self.status = 'stopped'
        Logger.info('LocationProvider: stopped')

    # ── Android GPS via plyer ────────────────────────────────────

    def _start_android(self, min_time_ms, min_distance_m):
        """Start the Android GPS provider."""
        try:
            from plyer import gps
            self._gps = gps
            gps.configure(
                on_location=self._on_android_location,
                on_status=self._on_android_status,
            )
            gps.start(minTime=min_time_ms, minDistance=min_distance_m)
            self.active = True
            self.status = 'acquiring'
            Logger.info('LocationProvider: Android GPS started')
        except Exception as e:
            Logger.error(f'LocationProvider: failed to start GPS: {e}')
            self.status = f'error: {e}'

    def _stop_android(self):
        """Stop the Android GPS provider."""
        if self._gps:
            try:
                self._gps.stop()
            except Exception as e:
                Logger.warning(f'LocationProvider: stop error: {e}')

    def _on_android_location(self, **kwargs):
        """Handle a GPS fix from plyer."""
        loc = {
            'latitude': kwargs.get('lat', 0.0),
            'longitude': kwargs.get('lon', 0.0),
            'altitude': kwargs.get('altitude', 0.0),
            'speed': kwargs.get('speed', 0.0),
            'bearing': kwargs.get('bearing', 0.0),
            'accuracy': kwargs.get('accuracy', 0.0),
        }
        self._update(loc)

    def _on_android_status(self, stype, status):
        """Handle GPS status changes."""
        Logger.info(f'LocationProvider: status {stype} = {status}')
        self.status = str(status)

    # ── Desktop simulation ───────────────────────────────────────

    def _start_simulation(self, min_time_ms):
        """Start simulated location updates for desktop dev."""
        interval = max(min_time_ms / 1000.0, 1.0)
        self._sim_event = Clock.schedule_interval(
            self._sim_tick, interval
        )
        self.active = True
        self.status = 'simulated'
        Logger.info('LocationProvider: desktop simulation started')

    def _stop_simulation(self):
        """Stop the desktop simulation."""
        if self._sim_event:
            self._sim_event.cancel()
            self._sim_event = None

    def _sim_tick(self, dt):
        """Generate a simulated GPS fix.

        Simulates cycling at ~20 km/h with slight heading drift.
        """
        # ~20 km/h ≈ 5.56 m/s
        speed_ms = 5.0 + random.uniform(-0.5, 0.5)
        # Heading drift
        self._sim_heading += random.uniform(-5, 5)
        self._sim_heading %= 360

        heading_rad = math.radians(self._sim_heading)
        # Approximate displacement in degrees
        # 1 degree latitude ≈ 111,320 m
        d_lat = (speed_ms * dt * math.cos(heading_rad)) / 111320.0
        d_lon = (speed_ms * dt * math.sin(heading_rad)) / (
            111320.0 * math.cos(math.radians(self._sim_lat))
        )

        self._sim_lat += d_lat
        self._sim_lon += d_lon

        loc = {
            'latitude': self._sim_lat,
            'longitude': self._sim_lon,
            'altitude': 50.0 + random.uniform(-1, 1),
            'speed': speed_ms,
            'bearing': self._sim_heading,
            'accuracy': 3.0 + random.uniform(0, 5),
        }
        self._update(loc)

    # ── Common ───────────────────────────────────────────────────

    def _update(self, loc):
        """Update properties and fire callback."""
        self.latitude = loc['latitude']
        self.longitude = loc['longitude']
        self.altitude = loc.get('altitude', 0.0)
        self.speed = loc.get('speed', 0.0)
        self.bearing = loc.get('bearing', 0.0)
        self.accuracy = loc.get('accuracy', 0.0)
        self.status = 'active'

        if self._callback:
            self._callback(loc)


def haversine(lat1, lon1, lat2, lon2):
    """Calculate the great-circle distance in metres between two points.

    Uses the Haversine formula.

    Args:
        lat1, lon1: First point in decimal degrees.
        lat2, lon2: Second point in decimal degrees.

    Returns:
        Distance in metres.
    """
    R = 6_371_000  # Earth radius in metres

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return R * c
