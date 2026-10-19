package org.cyclingtracker.cyclingtracker;

import android.bluetooth.le.ScanCallback;
import android.bluetooth.le.ScanResult;

public class CyclingTrackerScanCallback extends ScanCallback {
    private final BleCallbackListener listener;

    public CyclingTrackerScanCallback(BleCallbackListener listener) {
        this.listener = listener;
    }

    @Override
    public void onScanResult(int callbackType, ScanResult result) {
        notifyResult(result);
    }

    @Override
    public void onBatchScanResults(java.util.List<ScanResult> results) {
        for (ScanResult result : results) {
            notifyResult(result);
        }
    }

    @Override
    public void onScanFailed(int errorCode) {
        listener.onScanFailed(errorCode);
    }

    private void notifyResult(ScanResult result) {
        String address = result.getDevice().getAddress();
        String name = result.getDevice().getName();
        if (address != null) {
            listener.onScanResult(
                address,
                name == null ? "Heart-rate sensor" : name
            );
        }
    }
}
