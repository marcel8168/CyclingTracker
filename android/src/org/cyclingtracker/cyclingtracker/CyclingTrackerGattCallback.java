package org.cyclingtracker.cyclingtracker;

import android.bluetooth.BluetoothGatt;
import android.bluetooth.BluetoothGatt;
import android.bluetooth.BluetoothGattCallback;
import android.bluetooth.BluetoothGattCharacteristic;
import android.bluetooth.BluetoothGattDescriptor;
import android.bluetooth.BluetoothGattService;
import android.bluetooth.BluetoothProfile;
import android.bluetooth.BluetoothStatusCodes;
import android.os.Build;
import android.util.Log;

import java.util.UUID;

public class CyclingTrackerGattCallback extends BluetoothGattCallback {
    private static final String TAG = "CyclingTrackerGattCallback";
    private static final UUID HEART_RATE_SERVICE_UUID =
        UUID.fromString("0000180d-0000-1000-8000-00805f9b34fb");
    private static final UUID HEART_RATE_MEASUREMENT_UUID =
        UUID.fromString("00002a37-0000-1000-8000-00805f9b34fb");
    private static final UUID CLIENT_CHARACTERISTIC_CONFIG_UUID =
        UUID.fromString("00002902-0000-1000-8000-00805f9b34fb");

    private final BleCallbackListener listener;

    public CyclingTrackerGattCallback(BleCallbackListener listener) {
        this.listener = listener;
    }

    @Override
    public void onConnectionStateChange(
        BluetoothGatt gatt,
        int status,
        int newState
    ) {
        if (status == BluetoothGatt.GATT_SUCCESS
            && newState == BluetoothProfile.STATE_CONNECTED) {
            try {
                if (!gatt.discoverServices()) {
                    listener.onError("Could not start Bluetooth service discovery");
                }
            } catch (SecurityException | IllegalStateException exception) {
                Log.e(TAG, "Could not start service discovery", exception);
                listener.onError(
                    "Could not start Bluetooth service discovery: "
                    + exception.getMessage()
                );
            }
        }
        listener.onConnectionStateChange(status, newState);
    }

    @Override
    public void onServicesDiscovered(BluetoothGatt gatt, int status) {
        if (status != BluetoothGatt.GATT_SUCCESS) {
            listener.onServicesDiscovered(status, null);
            return;
        }

        try {
            BluetoothGattService service = gatt.getService(HEART_RATE_SERVICE_UUID);
            if (service == null) {
                listener.onServicesDiscovered(
                    status, "Device does not provide Heart Rate Service"
                );
                return;
            }

            BluetoothGattCharacteristic characteristic =
                service.getCharacteristic(HEART_RATE_MEASUREMENT_UUID);
            if (characteristic == null) {
                listener.onServicesDiscovered(
                    status, "Heart-rate measurement characteristic is missing"
                );
                return;
            }
            if (!gatt.setCharacteristicNotification(characteristic, true)) {
                listener.onServicesDiscovered(
                    status, "Could not subscribe to heart-rate measurements"
                );
                return;
            }

            BluetoothGattDescriptor descriptor =
                characteristic.getDescriptor(CLIENT_CHARACTERISTIC_CONFIG_UUID);
            if (descriptor == null) {
                listener.onServicesDiscovered(
                    status, "Heart-rate notification descriptor is missing"
                );
                return;
            }

            boolean writeStarted;
            if (Build.VERSION.SDK_INT >= 33) {
                writeStarted = gatt.writeDescriptor(
                    descriptor,
                    BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE
                ) == BluetoothStatusCodes.SUCCESS;
            } else {
                descriptor.setValue(
                    BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE
                );
                writeStarted = gatt.writeDescriptor(descriptor);
            }
            if (!writeStarted) {
                listener.onServicesDiscovered(
                    status, "Could not start heart-rate notification setup"
                );
                return;
            }

            Log.i(TAG, "Heart-rate notification descriptor write started");
            listener.onServicesDiscovered(status, "Enabling notifications");
        } catch (SecurityException | IllegalStateException exception) {
            Log.e(TAG, "Heart-rate notification setup failed", exception);
            listener.onError(
                "Heart-rate notification setup failed: "
                + exception.getMessage()
            );
        }
    }

    @Override
    public void onDescriptorWrite(
        BluetoothGatt gatt,
        BluetoothGattDescriptor descriptor,
        int status
    ) {
        listener.onDescriptorWrite(status);
    }

    @Override
    public void onCharacteristicChanged(
        BluetoothGatt gatt,
        BluetoothGattCharacteristic characteristic
    ) {
        reportHeartRate(characteristic.getValue());
    }

    @Override
    public void onCharacteristicChanged(
        BluetoothGatt gatt,
        BluetoothGattCharacteristic characteristic,
        byte[] value
    ) {
        reportHeartRate(value);
    }

    private void reportHeartRate(byte[] value) {
        if (value == null || value.length < 2) {
            Log.w(TAG, "Ignoring incomplete heart-rate measurement");
            return;
        }
        int flags = value[0] & 0xff;
        int bpm;
        if ((flags & 0x01) != 0) {
            if (value.length < 3) {
                Log.w(TAG, "Ignoring incomplete 16-bit heart-rate measurement");
                return;
            }
            bpm = (value[1] & 0xff) | ((value[2] & 0xff) << 8);
        } else {
            bpm = value[1] & 0xff;
        }
        listener.onHeartRate(bpm);
    }
}
