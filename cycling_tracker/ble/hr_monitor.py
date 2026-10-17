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

    def __init__(self, on_heart_rate=None, on_status=None, on_devices=None):
        self.on_heart_rate = on_heart_rate or (lambda _bpm, _timestamp: None)
        self.on_status = on_status or (lambda _status: None)
        self.on_devices = on_devices or (lambda _devices: None)
        self.status = 'Disconnected'
        self.devices = []
        self._scanner = None
        self._scan_callback = None
        self._gatt_callback = None
        self._gatt = None
        self._context = None
        self._connected_address = None

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
            manager = mActivity.getSystemService(Context.BLUETOOTH_SERVICE)
            adapter = manager.getAdapter()
            if adapter is None or not adapter.isEnabled():
                self._set_status('Bluetooth is disabled')
                return False
            self._context = mActivity
            self.devices = []
            monitor = self

            class ScanCallback(PythonJavaClass):
                __javainterfaces__ = ['android/bluetooth/le/ScanCallback']
                __javacontext__ = 'app'

                @java_method('(ILandroid/bluetooth/le/ScanResult;)V')
                def onScanResult(self, _callback_type, result):
                    device = result.getDevice()
                    address = device.getAddress()
                    name = device.getName()
                    if address:
                        Clock.schedule_once(
                            lambda _dt: monitor._add_device(
                                address, name or 'Heart-rate sensor'
                            ),
                            0
                        )

                @java_method('([Landroid/bluetooth/le/ScanResult;)V')
                def onBatchScanResults(self, results):
                    for result in results:
                        self.onScanResult(0, result)

                @java_method('(I)V')
                def onScanFailed(self, error_code):
                    Clock.schedule_once(
                        lambda _dt: monitor._set_status(
                            f'Bluetooth scan failed ({error_code})'
                        ),
                        0
                    )

            self._scan_callback = ScanCallback()
            self._scanner = adapter.getBluetoothLeScanner()
            if self._scanner is None:
                self._set_status('Bluetooth LE scanner is unavailable')
                return False
            self._scanner.startScan(self._scan_callback)
            self._set_status('Scanning for heart-rate sensors…')
            Clock.schedule_once(lambda _dt: self.stop_scan(), timeout_seconds)
            return True
        except Exception as exc:
            Logger.exception(f'HeartRateMonitor: scan failed: {exc}')
            self._set_status(f'Scan error: {exc}')
            return False

    def stop_scan(self):
        if self._scanner is not None and self._scan_callback is not None:
            try:
                self._scanner.stopScan(self._scan_callback)
            except Exception as exc:
                Logger.warning(f'HeartRateMonitor: stop scan failed: {exc}')
        self._scanner = None
        self._scan_callback = None
        if self.status.startswith('Scanning'):
            self._set_status('No heart-rate sensor found' if not self.devices else
                             'Select a heart-rate sensor')

    def connect(self, address):
        """Connect to a discovered BLE device and subscribe to measurements."""
        if platform != 'android':
            self._set_status('Bluetooth connection is available on Android')
            return False
        try:
            from kivy.clock import Clock
            from jnius import autoclass, PythonJavaClass, java_method

            self.stop_scan()
            Context = autoclass('android.content.Context')
            manager = self._context.getSystemService(Context.BLUETOOTH_SERVICE)
            device = manager.getAdapter().getRemoteDevice(address)
            monitor = self

            class GattCallback(PythonJavaClass):
                __javainterfaces__ = ['android/bluetooth/BluetoothGattCallback']
                __javacontext__ = 'app'

                @java_method(
                    '(Landroid/bluetooth/BluetoothGatt;II)V'
                )
                def onConnectionStateChange(self, gatt, status, new_state):
                    BluetoothProfile = autoclass(
                        'android.bluetooth.BluetoothProfile'
                    )
                    if status == 0 and new_state == BluetoothProfile.STATE_CONNECTED:
                        Clock.schedule_once(
                            lambda _dt: monitor._set_status('Connected; discovering service'),
                            0
                        )
                        gatt.discoverServices()
                    else:
                        Clock.schedule_once(
                            lambda _dt: monitor._on_disconnected(gatt, status),
                            0
                        )

                @java_method('(Landroid/bluetooth/BluetoothGatt;I)V')
                def onServicesDiscovered(self, gatt, status):
                    if status != 0:
                        Clock.schedule_once(
                            lambda _dt: monitor._set_status(
                                f'Service discovery failed ({status})'
                            ),
                            0
                        )
                        return
                    service = gatt.getService(
                        autoclass('java.util.UUID').fromString(
                            HEART_RATE_SERVICE_UUID
                        )
                    )
                    if service is None:
                        Clock.schedule_once(
                            lambda _dt: monitor._set_status(
                                'Device does not provide Heart Rate Service'
                            ),
                            0
                        )
                        return
                    characteristic = service.getCharacteristic(
                        autoclass('java.util.UUID').fromString(
                            HEART_RATE_MEASUREMENT_UUID
                        )
                    )
                    if characteristic is None or not gatt.setCharacteristicNotification(
                        characteristic, True
                    ):
                        Clock.schedule_once(
                            lambda _dt: monitor._set_status(
                                'Could not subscribe to heart-rate measurements'
                            ),
                            0
                        )
                        return
                    descriptor = characteristic.getDescriptor(
                        autoclass('java.util.UUID').fromString(
                            CLIENT_CHARACTERISTIC_CONFIG_UUID
                        )
                    )
                    if descriptor is None:
                        Clock.schedule_once(
                            lambda _dt: monitor._set_status(
                                'Heart-rate notification descriptor is missing'
                            ),
                            0
                        )
                        return
                    from jnius import Array
                    descriptor.setValue(Array('b', [1, 0]))
                    if not gatt.writeDescriptor(descriptor):
                        Clock.schedule_once(
                            lambda _dt: monitor._set_status(
                                'Could not enable heart-rate notifications'
                            ),
                            0
                        )

                @java_method(
                    '(Landroid/bluetooth/BluetoothGatt;'
                    'Landroid/bluetooth/BluetoothGattDescriptor;I)V'
                )
                def onDescriptorWrite(self, _gatt, _descriptor, status):
                    message = (
                        'Connected' if status == 0
                        else f'Notification setup failed ({status})'
                    )
                    Clock.schedule_once(
                        lambda _dt: monitor._set_status(message), 0
                    )

                @java_method(
                    '(Landroid/bluetooth/BluetoothGatt;'
                    'Landroid/bluetooth/BluetoothGattCharacteristic;)V'
                )
                def onCharacteristicChanged(self, _gatt, characteristic):
                    data = characteristic.getValue()
                    if data is None:
                        return
                    try:
                        bpm = parse_heart_rate_measurement(data)
                    except ValueError as exc:
                        Logger.warning(f'HeartRateMonitor: invalid measurement: {exc}')
                        return
                    Clock.schedule_once(
                        lambda _dt: monitor._on_measurement(bpm), 0
                    )

            self._connected_address = address
            self._gatt_callback = GattCallback()
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
            try:
                self._gatt.disconnect()
                self._gatt.close()
            except Exception as exc:
                Logger.warning(f'HeartRateMonitor: disconnect failed: {exc}')
        self._gatt = None
        self._gatt_callback = None
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

    def _on_disconnected(self, gatt, status):
        if self._gatt is gatt:
            self._gatt = None
            self._gatt_callback = None
            self._set_status(
                'Disconnected' if status == 0 else f'Disconnected ({status})'
            )

    def _set_status(self, status):
        self.status = status
        self.on_status(status)
