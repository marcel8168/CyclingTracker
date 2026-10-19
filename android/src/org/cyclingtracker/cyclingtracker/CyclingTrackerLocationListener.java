package org.cyclingtracker.cyclingtracker;

import android.location.Location;
import android.location.LocationListener;
import android.os.Bundle;

import java.util.List;

public class CyclingTrackerLocationListener implements LocationListener {
    private final LocationCallbackListener listener;

    public CyclingTrackerLocationListener(LocationCallbackListener listener) {
        this.listener = listener;
    }

    @Override
    public void onLocationChanged(Location location) {
        listener.onLocation(location);
    }

    @Override
    public void onLocationChanged(List<Location> locations) {
        for (Location location : locations) {
            listener.onLocation(location);
        }
    }

    @Override
    public void onProviderEnabled(String provider) {
    }

    @Override
    public void onProviderDisabled(String provider) {
    }

    @Override
    public void onStatusChanged(String provider, int status, Bundle extras) {
    }
}
