package org.cyclingtracker.cyclingtracker;

public interface BleCallbackListener {
    void onScanResult(String address, String name);
    void onScanFailed(int errorCode);
    void onConnectionStateChange(int status, int newState);
    void onServicesDiscovered(int status, String message);
    void onDescriptorWrite(int status);
    void onHeartRate(int bpm);
    void onError(String message);
}
