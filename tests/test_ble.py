"""Tests for BLE heart-rate scanning and payload decoding."""

import sys
import types
import unittest
from unittest.mock import patch

import cycling_tracker.ble.hr_monitor as hr_monitor
from cycling_tracker.ble.hr_monitor import (
    HeartRateMonitor,
    parse_heart_rate_measurement,
)


class HeartRatePayloadTests(unittest.TestCase):
    def test_scan_filters_for_heart_rate_service(self):
        class FakeScanFilterBuilder:
            def setServiceUuid(self, service_uuid):
                self.service_uuid = service_uuid
                return self

            def build(self):
                return self.service_uuid

        class FakeScanSettingsBuilder:
            def build(self):
                return 'scan-settings'

        class FakeArrayList(list):
            def add(self, value):
                self.append(value)

        class FakeScanner:
            def startScan(self, filters, settings, callback):
                self.filters = filters
                self.settings = settings
                self.callback = callback

            def stopScan(self, _callback):
                pass

        class FakeAdapter:
            def __init__(self, scanner):
                self.scanner = scanner

            def isEnabled(self):
                return True

            def getBluetoothLeScanner(self):
                return self.scanner

        class FakeUuid:
            @staticmethod
            def fromString(value):
                return value

        class FakeParcelUuid:
            def __init__(self, value):
                self.value = value

        class FakeContext:
            BLUETOOTH_SERVICE = 'bluetooth'

        scanner = FakeScanner()
        adapter = FakeAdapter(scanner)
        activity = types.SimpleNamespace(
            getSystemService=lambda _service: types.SimpleNamespace(
                getAdapter=lambda: adapter
            )
        )
        fake_jnius = types.ModuleType('jnius')
        fake_jnius.autoclass = lambda name: {
            'android.content.Context': FakeContext,
            'android.bluetooth.le.ScanFilter$Builder': FakeScanFilterBuilder,
            'android.bluetooth.le.ScanSettings$Builder':
                FakeScanSettingsBuilder,
            'android.os.ParcelUuid': FakeParcelUuid,
            'java.util.UUID': FakeUuid,
            'java.util.ArrayList': FakeArrayList,
        }[name]
        fake_jnius.PythonJavaClass = object
        fake_jnius.java_method = lambda _signature: lambda method: method
        fake_android = types.ModuleType('android')
        fake_android.mActivity = activity
        fake_clock = types.ModuleType('kivy.clock')
        fake_clock.Clock = types.SimpleNamespace(
            schedule_once=lambda _callback, _timeout: None
        )

        with patch.object(hr_monitor, 'platform', 'android'), patch.dict(
            sys.modules, {
                'jnius': fake_jnius,
                'android': fake_android,
                'kivy.clock': fake_clock,
            }
        ):
            monitor = HeartRateMonitor(dispatch=lambda callback: callback())

            self.assertTrue(monitor.scan())

        self.assertEqual(len(scanner.filters), 1)
        self.assertEqual(
            scanner.filters[0].value,
            '0000180d-0000-1000-8000-00805f9b34fb',
        )
        self.assertEqual(scanner.settings, 'scan-settings')
        self.assertIs(scanner.callback, monitor._scan_callback)

    @staticmethod
    def _connect_with_api_level(api_level):
        class FakeGatt:
            def __init__(self):
                self.closed = False
                self.disconnected = False

            def disconnect(self):
                self.disconnected = True

            def close(self):
                self.closed = True

        class FakeDevice:
            def connectGatt(self, _context, _auto_connect, callback, _transport):
                self.callback = callback
                self.gatt = FakeGatt()
                return self.gatt

        device = FakeDevice()
        manager = types.SimpleNamespace(
            getAdapter=lambda: types.SimpleNamespace(
                getRemoteDevice=lambda _address: device
            )
        )
        context = types.SimpleNamespace(
            getSystemService=lambda _service: manager
        )

        class FakeContext:
            BLUETOOTH_SERVICE = 'bluetooth'

        fake_jnius = types.ModuleType('jnius')
        fake_jnius.autoclass = lambda name: {
            'android.content.Context': FakeContext,
            'android.os.Build': types.SimpleNamespace(
                VERSION=types.SimpleNamespace(SDK_INT=api_level)
            ),
            'android.bluetooth.BluetoothDevice': types.SimpleNamespace(
                TRANSPORT_LE=2
            ),
        }[name]
        fake_jnius.PythonJavaClass = object
        fake_jnius.java_method = lambda _signature: lambda method: method
        fake_android = types.ModuleType('android')

        with patch.object(hr_monitor, 'platform', 'android'), patch.dict(
            sys.modules, {'jnius': fake_jnius, 'android': fake_android}
        ):
            monitor = HeartRateMonitor(dispatch=lambda callback: callback())
            monitor._gatt = FakeGatt()
            previous_gatt = monitor._gatt
            connected = monitor.connect('sensor', context=context)

        return monitor, device, previous_gatt, connected

    def test_connect_releases_previous_gatt_and_uses_api_specific_callback(self):
        for api_level in (26, 33):
            with self.subTest(api_level=api_level):
                measurements = []
                monitor, device, previous_gatt, connected = (
                    self._connect_with_api_level(api_level)
                )
                monitor.on_heart_rate = lambda bpm, _timestamp: measurements.append(
                    bpm
                )

                self.assertTrue(connected)
                self.assertTrue(previous_gatt.disconnected)
                self.assertTrue(previous_gatt.closed)
                if api_level >= 33:
                    device.callback.onCharacteristicChanged(
                        device.gatt, None, bytes([0x00, 146])
                    )
                else:
                    characteristic = types.SimpleNamespace(
                        getValue=lambda: bytes([0x00, 146])
                    )
                    device.callback.onCharacteristicChanged(
                        device.gatt, characteristic
                    )

                self.assertEqual(measurements, [146])

    def test_decodes_uint8_measurement(self):
        self.assertEqual(parse_heart_rate_measurement(bytes([0x00, 147])), 147)

    def test_decodes_uint16_measurement(self):
        self.assertEqual(
            parse_heart_rate_measurement(bytes([0x01, 0x2c, 0x01])), 300
        )

    def test_rejects_incomplete_measurement(self):
        with self.assertRaises(ValueError):
            parse_heart_rate_measurement(bytes([0x01, 10]))

    def test_api_33_payload_is_processed(self):
        measurements = []
        monitor = HeartRateMonitor(
            on_heart_rate=lambda bpm, _timestamp: measurements.append(bpm),
            dispatch=lambda callback: callback(),
        )

        monitor._on_characteristic_changed(bytes([0x00, 147]))

        self.assertEqual(measurements, [147])

    def test_disconnection_closes_active_gatt(self):
        class FakeGatt:
            def __init__(self):
                self.closed = False

            def close(self):
                self.closed = True

        gatt = FakeGatt()
        monitor = HeartRateMonitor()
        monitor._gatt = gatt
        monitor._gatt_callback = object()
        monitor._connected_address = 'sensor'

        monitor._on_disconnected(gatt, 0)

        self.assertTrue(gatt.closed)
        self.assertIsNone(monitor._gatt)
        self.assertIsNone(monitor._gatt_callback)
        self.assertIsNone(monitor._connected_address)
        self.assertEqual(monitor.status, 'Disconnected')

    def test_disconnect_closes_gatt_even_if_disconnect_raises(self):
        class FakeGatt:
            def __init__(self):
                self.closed = False

            def disconnect(self):
                raise RuntimeError('disconnect failed')

            def close(self):
                self.closed = True

        gatt = FakeGatt()
        monitor = HeartRateMonitor()
        monitor._gatt = gatt

        monitor.disconnect()

        self.assertTrue(gatt.closed)
        self.assertIsNone(monitor._gatt)


if __name__ == '__main__':
    unittest.main()
