"""Android BLE client for the Bluetooth SIG Heart Rate Service."""

import logging
import sys

try:
    from kivy.logger import Logger
    from kivy.utils import platform
except ModuleNotFoundError:
    Logger = logging.getLogger('cycling_tracker.ble')
    platform = 'android' if sys.platform == 'android' else sys.platform

HEART_RATE_SERVICE_UUID = '0000180d-0000-1000-8000-00805f9b34fb'
HEART_RATE_MEASUREMENT_UUID = '00002a37-0000-1000-8000-00805f9b34fb'
CLIENT_CHARACTERISTIC_CONFIG_UUID = '00002902-0000-1000-8000-00805f9b34fb'


def _create_callback_listener(monitor, PythonJavaClass, java_method):
    class CallbackListener(PythonJavaClass):
        __javainterfaces__ = [
            'org/cyclingtracker/cyclingtracker/BleCallbackListener'
        ]
        __javacontext__ = 'app'

        @java_method('(Ljava/lang/String;Ljava/lang/String;)V')
        def onScanResult(self, address, name):
            try:
                monitor._dispatch(
                    lambda: monitor._add_device(address, name)
                )
            except Exception:
                Logger.exception('HeartRateMonitor: scan-result callback failed')

        @java_method('(I)V')
        def onScanFailed(self, error_code):
            try:
                monitor._dispatch(
                    lambda: monitor._set_status(
                        f'Bluetooth scan failed ({error_code})'
                    )
                )
            except Exception:
                Logger.exception('HeartRateMonitor: scan-failed callback failed')

        @java_method(
            '(II)V'
        )
        def onConnectionStateChange(self, status, new_state):
            try:
                monitor._dispatch(
                    lambda: monitor._on_connection_state_change(
                        status, new_state
                    )
                )
            except Exception:
                Logger.exception(
                    'HeartRateMonitor: connection-state callback failed'
                )

        @java_method('(ILjava/lang/String;)V')
        def onServicesDiscovered(self, status, message):
            try:
                monitor._dispatch(
                    lambda: monitor._on_services_discovered(status, message)
                )
            except Exception:
                Logger.exception(
                    'HeartRateMonitor: service-discovery callback failed'
                )

        @java_method('(I)V')
        def onDescriptorWrite(self, status):
            try:
                monitor._dispatch(
                    lambda: monitor._on_descriptor_write(status)
                )
            except Exception:
                Logger.exception('HeartRateMonitor: descriptor-write callback failed')

        @java_method('(I)V')
        def onHeartRate(self, bpm):
            try:
                monitor._dispatch(lambda: monitor._on_measurement(bpm))
            except Exception:
                Logger.exception('HeartRateMonitor: measurement callback failed')

        @java_method('(Ljava/lang/String;)V')
        def onError(self, message):
            try:
                monitor._dispatch(
                    lambda: monitor._set_status(f'Bluetooth error: {message}')
                )
            except Exception:
                Logger.exception('HeartRateMonitor: error callback failed')

    return CallbackListener()


def parse_heart_rate_measurement(data):
    """Decode the Heart Rate Measurement characteristic value."""
    if data is None or len(data) < 2:
        raise ValueError('heart-rate measurement is too short')
    flags = data[0] & 0xff
    if flags & 0x01:
        if len(data) < 3:
            raise ValueError('16-bit heart-rate measurement is incomplete')
        return (data[1] & 0xff) | ((data[2] & 0xff) << 8)
    return data[1] & 0xff


class HeartRateMonitor:
    """Scan, connect, and receive measurements from a BLE heart-rate strap."""

    def __init__(self, on_heart_rate=None, on_status=None, on_devices=None,
                 dispatch=None):
        self.on_heart_rate = on_heart_rate or (lambda _bpm, _timestamp: None)
        self.on_status = on_status or (lambda _status: None)
        self.on_devices = on_devices or (lambda _devices: None)
        self._dispatch = dispatch or self._dispatch_to_ui
        self.status = 'Disconnected'
        self.devices = []
        self._scanner = None
        self._scan_callback = None
        self._scan_listener = None
        self._scan_timeout_event = None
        self._gatt_callback = None
        self._gatt_listener = None
        self._gatt = None
        self._context = None
        self._connected_address = None

    @staticmethod
    def _dispatch_to_ui(callback):
        from kivy.clock import Clock
        Clock.schedule_once(lambda _dt: callback(), 0)

    def scan(self, timeout_seconds=12):
        """Begin a BLE scan, reporting discovered devices to the UI."""
        if platform != 'android':
            self._set_status('Bluetooth scanning is available on Android')
            return False
        try:
            from kivy.clock import Clock
            from jnius import autoclass, PythonJavaClass, java_method
            from android import mActivity

            Context = autoclass('android.content.Context')
            ScanFilterBuilder = autoclass(
                'android.bluetooth.le.ScanFilter$Builder'
            )
            ScanSettingsBuilder = autoclass(
                'android.bluetooth.le.ScanSettings$Builder'
            )
            ParcelUuid = autoclass('android.os.ParcelUuid')
            UUID = autoclass('java.util.UUID')
            ArrayList = autoclass('java.util.ArrayList')
            manager = mActivity.getSystemService(Context.BLUETOOTH_SERVICE)
            adapter = manager.getAdapter()
            if adapter is None or not adapter.isEnabled():
                self._set_status('Bluetooth is disabled')
                return False
            self._context = mActivity
            self.devices = []
            self._scan_listener = _create_callback_listener(
                self, PythonJavaClass, java_method
            )
            ScanCallback = autoclass(
                'org.cyclingtracker.cyclingtracker.'
                'CyclingTrackerScanCallback'
            )
            self._scan_callback = ScanCallback(self._scan_listener)
            self._scanner = adapter.getBluetoothLeScanner()
            if self._scanner is None:
                self._set_status('Bluetooth LE scanner is unavailable')
                return False
            scan_filter = ScanFilterBuilder().setServiceUuid(
                ParcelUuid(UUID.fromString(HEART_RATE_SERVICE_UUID))
            ).build()
            filters = ArrayList()
            filters.add(scan_filter)
            scan_settings = ScanSettingsBuilder().build()
            self._scanner.startScan(
                filters, scan_settings, self._scan_callback
            )
            self._set_status('Scanning for heart-rate sensors…')
            self._scan_timeout_event = Clock.schedule_once(
                lambda _dt: self.stop_scan(), timeout_seconds
            )
            return True
        except Exception as exc:
            Logger.exception(f'HeartRateMonitor: scan failed: {exc}')
            self._set_status(f'Scan error: {exc}')
            return False

    def stop_scan(self):
        if self._scan_timeout_event is not None:
            self._scan_timeout_event.cancel()
            self._scan_timeout_event = None
        if self._scanner is not None and self._scan_callback is not None:
            try:
                self._scanner.stopScan(self._scan_callback)
            except Exception as exc:
                Logger.warning(f'HeartRateMonitor: stop scan failed: {exc}')
        self._scanner = None
        self._scan_callback = None
        self._scan_listener = None
        if self.status.startswith('Scanning'):
            self._set_status('No heart-rate sensor found' if not self.devices else
                             'Select a heart-rate sensor')

    def connect(self, address, context=None):
        """Connect to a discovered BLE device and subscribe to measurements."""
        if platform != 'android':
            self._set_status('Bluetooth connection is available on Android')
            return False
        try:
            from jnius import autoclass, PythonJavaClass, java_method

            self.stop_scan()
            if self._gatt is not None:
                self.disconnect()
            Context = autoclass('android.content.Context')
            if context is not None:
                self._context = context
            if self._context is None:
                raise RuntimeError('Bluetooth context is unavailable; scan first')
            manager = self._context.getSystemService(Context.BLUETOOTH_SERVICE)
            device = manager.getAdapter().getRemoteDevice(address)
            self._connected_address = address
            self._gatt_listener = _create_callback_listener(
                self, PythonJavaClass, java_method
            )
            GattCallback = autoclass(
                'org.cyclingtracker.cyclingtracker.'
                'CyclingTrackerGattCallback'
            )
            self._gatt_callback = GattCallback(self._gatt_listener)
            BluetoothDevice = autoclass('android.bluetooth.BluetoothDevice')
            self._gatt = device.connectGatt(
                self._context, False, self._gatt_callback,
                BluetoothDevice.TRANSPORT_LE
            )
            if self._gatt is None:
                self._set_status('Could not initiate Bluetooth connection')
                return False
            self._set_status('Connecting…')
            return True
        except Exception as exc:
            Logger.exception(f'HeartRateMonitor: connection failed: {exc}')
            self._set_status(f'Connection error: {exc}')
            return False

    def disconnect(self):
        self.stop_scan()
        if self._gatt is not None:
            self._release_gatt(self._gatt, disconnect=True)
        self._gatt = None
        self._gatt_callback = None
        self._gatt_listener = None
        self._connected_address = None
        self._set_status('Disconnected')

    def _add_device(self, address, name):
        if any(device['address'] == address for device in self.devices):
            return
        self.devices.append({'address': address, 'name': name})
        self.on_devices(list(self.devices))
        self._set_status('Select a heart-rate sensor')

    def _on_measurement(self, bpm):
        if 1 <= bpm <= 255:
            self.on_heart_rate(bpm, None)
        else:
            Logger.warning(
                f'HeartRateMonitor: ignoring out-of-range heart rate ({bpm})'
            )

    def _on_characteristic_changed(self, data):
        if data is None:
            return
        try:
            bpm = parse_heart_rate_measurement(data)
        except ValueError as exc:
            Logger.warning(f'HeartRateMonitor: invalid measurement: {exc}')
            return
        self._dispatch(lambda: self._on_measurement(bpm))

    def _on_connection_state_change(self, status, new_state):
        Logger.info(
            'HeartRateMonitor: GATT connection callback '
            f'status={status} state={new_state}'
        )
        if status == 0 and new_state == 2:
            self._set_status('Connected; discovering service')
        elif new_state == 0:
            self._on_disconnected(status)

    def _on_services_discovered(self, status, message):
        Logger.info(
            'HeartRateMonitor: GATT service discovery '
            f'status={status} message={message}'
        )
        if status != 0:
            self._set_status(f'Service discovery failed ({status})')
        elif message:
            self._set_status(message)

    def _on_descriptor_write(self, status):
        Logger.info(f'HeartRateMonitor: notification descriptor status={status}')
        self._set_status(
            'Connected' if status == 0
            else f'Notification setup failed ({status})'
        )

    def _on_disconnected(self, status):
        if self._gatt is not None:
            self._release_gatt(self._gatt)
            self._gatt = None
            self._gatt_callback = None
            self._gatt_listener = None
            self._connected_address = None
        self._set_status(
            'Disconnected' if status == 0 else f'Disconnected ({status})'
        )

    @staticmethod
    def _release_gatt(gatt, disconnect=False):
        if disconnect:
            try:
                gatt.disconnect()
            except Exception as exc:
                Logger.warning(f'HeartRateMonitor: GATT disconnect failed: {exc}')
        try:
            gatt.close()
        except Exception as exc:
            Logger.warning(f'HeartRateMonitor: GATT close failed: {exc}')

    def _set_status(self, status):
        self.status = status
        self.on_status(status)
