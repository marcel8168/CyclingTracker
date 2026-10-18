"""Android foreground GPS and BLE recorder for screen-off ride tracking."""

import math
import queue
import time
from datetime import datetime, timezone

from kivy.logger import Logger
from kivy.utils import platform

from cycling_tracker.location import haversine
from cycling_tracker.ble.hr_monitor import HeartRateMonitor
from cycling_tracker.models.database import Database


class _LocationListener:
    """Create and retain the Java LocationListener used by Android."""

    def __new__(cls, on_location, PythonJavaClass, java_method):
        class Listener(PythonJavaClass):
            __javainterfaces__ = ['android/location/LocationListener']
            __javacontext__ = 'app'

            @java_method('(Landroid/location/Location;)V')
            def onLocationChanged(self, location):
                on_location(location)

            @java_method(
                '(Ljava/lang/String;ILandroid/os/Bundle;)V'
            )
            def onStatusChanged(self, _provider, _status, _extras):
                pass

            @java_method('(Ljava/lang/String;)V')
            def onProviderEnabled(self, _provider):
                Logger.info('RideService: GPS provider enabled')

            @java_method('(Ljava/lang/String;)V')
            def onProviderDisabled(self, _provider):
                Logger.warning('RideService: GPS provider disabled')

        return Listener()


def _record_location(db, ride_id, location, previous):
    lat = location['latitude']
    lon = location['longitude']
    accuracy = location['accuracy']
    if (
        not math.isfinite(lat)
        or not math.isfinite(lon)
        or not -90 <= lat <= 90
        or not -180 <= lon <= 180
        or not math.isfinite(accuracy)
        or accuracy > 50
    ):
        return previous

    distance_total, last_lat, last_lon = previous
    if last_lat is not None and last_lon is not None:
        delta = haversine(last_lat, last_lon, lat, lon)
        if delta < 500:
            distance_total += delta

    timestamp = datetime.now(timezone.utc).isoformat()
    db.insert_sample(
        ride_id,
        latitude=lat,
        longitude=lon,
        altitude=location['altitude'],
        speed=location['speed'],
        bearing=location['bearing'],
        accuracy=accuracy,
        timestamp=timestamp,
    )
    db.update_ride_distance(ride_id, distance_total)
    db.conn.commit()
    Logger.debug(f'RideService: recorded GPS fix for ride {ride_id}')
    return distance_total, lat, lon


def _record_heart_rate(db, ride_id, measurement):
    bpm, timestamp = measurement
    db.insert_heart_rate(ride_id, bpm, timestamp=timestamp)
    Logger.debug(f'RideService: recorded heart-rate sample for ride {ride_id}')


def _acquire_wake_lock(service, Context):
    from jnius import autoclass

    PowerManager = autoclass('android.os.PowerManager')
    power_manager = service.getSystemService(Context.POWER_SERVICE)
    wake_lock = power_manager.newWakeLock(
        PowerManager.PARTIAL_WAKE_LOCK, 'CyclingTracker:RideRecording'
    )
    wake_lock.setReferenceCounted(False)
    wake_lock.acquire()
    Logger.info('RideService: partial wake lock acquired')
    return wake_lock


def _start_foreground_notification(service, Context):
    """Attach an Android notification so the OS accepts the service."""
    from jnius import autoclass

    NotificationManager = autoclass('android.app.NotificationManager')
    NotificationChannel = autoclass('android.app.NotificationChannel')
    NotificationBuilder = autoclass('android.app.Notification$Builder')
    Build = autoclass('android.os.Build$VERSION')
    ServiceInfo = autoclass('android.content.pm.ServiceInfo')

    channel_id = 'cycling_tracker_recorder'
    channel_name = 'Ride Recording'
    notification_manager = service.getSystemService(Context.NOTIFICATION_SERVICE)
    notification_manager.createNotificationChannel(
        NotificationChannel(
            channel_id,
            channel_name,
            NotificationManager.IMPORTANCE_LOW,
        )
    )

    builder = NotificationBuilder(service, channel_id)
    builder.setContentTitle('CyclingTracker')
    builder.setContentText('Recording ride in background…')
    builder.setOngoing(True)
    builder.setOnlyAlertOnce(True)
    builder.setSmallIcon(service.getApplicationInfo().icon)
    notification = builder.build()

    if Build.SDK_INT >= 29:
        service.startForeground(
            1001,
            notification,
            ServiceInfo.FOREGROUND_SERVICE_TYPE_LOCATION,
        )
    else:
        service.startForeground(1001, notification)

    Logger.info('RideService: foreground notification started')


def main():
    """Run until the active ride ends or Android stops this service."""
    if platform != 'android':
        Logger.warning('RideService: Android foreground service only')
        return

    from jnius import autoclass, PythonJavaClass, java_method

    PythonService = autoclass('org.kivy.android.PythonService')
    service = PythonService.mService
    LocationManager = autoclass('android.location.LocationManager')
    Context = autoclass('android.content.Context')
    _start_foreground_notification(service, Context)
    manager = service.getSystemService(Context.LOCATION_SERVICE)
    db = Database()
    db.open()
    listener = None
    heart_rate_monitor = None
    wake_lock = None
    ride_id = None
    location_queue = queue.SimpleQueue()
    heart_rate_queue = queue.SimpleQueue()
    location_state = (0.0, None, None)
    last_elapsed_write = 0

    def on_location(location):
        try:
            timestamp = datetime.fromtimestamp(
                location.getTime() / 1000, timezone.utc
            ).isoformat()
            altitude = float(location.getAltitude())
            speed = float(location.getSpeed())
            bearing = float(location.getBearing())
            location_queue.put({
                'latitude': float(location.getLatitude()),
                'longitude': float(location.getLongitude()),
                'altitude': altitude if math.isfinite(altitude) else None,
                'speed': max(0.0, speed) if math.isfinite(speed) else 0.0,
                'bearing': bearing if math.isfinite(bearing) else None,
                'accuracy': float(location.getAccuracy()),
                'timestamp': timestamp,
            })
        except Exception:
            Logger.exception('RideService: could not queue GPS fix')

    try:
        active = db.get_active_ride()
        if active is None:
            Logger.warning('RideService: no active ride to record')
            return
        ride_id = active['id']
        wake_lock = _acquire_wake_lock(service, Context)
        ble_address = db.get_setting('ble_device_address')
        if ble_address:
            heart_rate_monitor = HeartRateMonitor(
                on_heart_rate=lambda bpm, timestamp: heart_rate_queue.put(
                    (bpm, timestamp)
                ),
                on_status=lambda status: Logger.info(
                    f'RideService: BLE {status}'
                ),
                dispatch=lambda callback: callback(),
            )
            if not heart_rate_monitor.connect(ble_address, context=service):
                Logger.warning('RideService: could not connect heart-rate sensor')
        elapsed_at_service_start = int(active['total_elapsed_s'] or 0)
        service_started = time.monotonic()
        location_state = (
            float(active['total_distance_m'] or 0),
            None,
            None,
        )
        last = db.get_last_sample(ride_id)
        if last:
            location_state = (
                location_state[0],
                float(last['latitude']),
                float(last['longitude']),
            )

        listener = _LocationListener(on_location, PythonJavaClass, java_method)
        manager.requestLocationUpdates(
            LocationManager.GPS_PROVIDER, 1000, 2.0, listener
        )
        Logger.info(f'RideService: GPS foreground tracking started for {ride_id}')

        while True:
            active = db.get_ride(ride_id)
            if active is None or active['status'] != 'active':
                break
            while not location_queue.empty():
                try:
                    fix = location_queue.get_nowait()
                except queue.Empty:
                    break
                location_state = _record_location(
                    db, ride_id, fix, location_state
                )
            while not heart_rate_queue.empty():
                try:
                    measurement = heart_rate_queue.get_nowait()
                except queue.Empty:
                    break
                _record_heart_rate(db, ride_id, measurement)
            elapsed = elapsed_at_service_start + int(
                time.monotonic() - service_started
            )
            if elapsed >= last_elapsed_write + 1:
                db.update_ride_elapsed(ride_id, elapsed)
                db.update_ride_distance(ride_id, location_state[0])
                db.conn.commit()
                last_elapsed_write = elapsed
            time.sleep(1)
    except Exception:
        Logger.exception('RideService: foreground tracking failed')
        raise
    finally:
        if heart_rate_monitor is not None:
            heart_rate_monitor.disconnect()
        if listener is not None:
            try:
                manager.removeUpdates(listener)
            except Exception:
                Logger.exception('RideService: could not remove GPS listener')
        if wake_lock is not None:
            try:
                if wake_lock.isHeld():
                    wake_lock.release()
                    Logger.info('RideService: partial wake lock released')
            except Exception:
                Logger.exception('RideService: could not release wake lock')
        db.close()
        Logger.info('RideService: stopped')


if __name__ == '__main__':
    main()
