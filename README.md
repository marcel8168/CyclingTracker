# CyclingTracker

A Python-based Android cycling tracker built with [Kivy](https://kivy.org/)
and packaged with [Buildozer](https://buildozer.readthedocs.io/).

## Features

- GPS location, speed, altitude, distance, and elapsed-time recording
- Standard Bluetooth LE Heart Rate Service support (service UUID `0x180D`)
- Local SQLite ride and sensor data persistence
- Android foreground service for screen-off GPS and BLE heart-rate recording
- Ride history with GPX 1.1 export and Garmin heart-rate track-point extensions
- Offline operation; no accounts or cloud sync
- Desktop GPS simulation and mocked permissions for UI development

## Requirements

### Development

- Python 3.10+
- Kivy 2.3+

### Android build

- Buildozer
- Android SDK/NDK (managed by Buildozer)
- Java 17
- On Debian/Ubuntu-based hosts, install the host build dependencies:
  `sudo apt install autoconf libffi-dev libssl-dev libtool`. `libffi-dev` and
  `libssl-dev` are needed to build the host Python `_ctypes` and SSL modules;
  Autoconf and Libtool provide `autoreconf` and `libtoolize` for libffi.

### Android device

- Android 8.0+ (API 26)
- Location Services
- Bluetooth LE heart-rate sensor (optional)

## Quick Start

Run on desktop:

```bash
python -m pip install "kivy==2.3.0"
python main.py
```

Desktop mode simulates GPS in Cologne. BLE scanning and screen-off recording
require Android hardware.

Run the host-side tests:

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -v
```

Build and run on Android:

```bash
python -m pip install buildozer
buildozer android debug deploy run
```

The Buildozer configuration pins python-for-android to a Python 3.11 release;
this is needed because Kivy 2.3.0 does not build against the Python 3.14
headers selected by newer python-for-android revisions.

On Android 10+, grant background location for uninterrupted screen-off
recording. Android 11+ may require enabling "Allow all the time" from the
system app-permissions page after the initial prompt. During a ride, the app
uses a foreground service and persistent notification. Select a heart-rate
sensor before starting a ride; the foreground service owns its BLE connection
and writes measurements alongside GPS data while recording. The service holds
a partial wake lock until recording stops. Validate screen-off behavior on a
physical device; emulator tests cannot fully reproduce device power-management
behavior or sensor interoperability.

## Local data and export

On Android, rides and samples are stored in the app-private SQLite database.
On POSIX desktops, the database directory is restricted to the current user
(`0700`) and the database file to the current user (`0600`). These permissions
limit access by other local accounts but do not encrypt the data at rest.
GPX exports are saved under `Downloads/CyclingTracker` on Android 10+, in the
app's external `Documents` directory on earlier Android versions, and in the
app's `exports` directory on desktop.

## Project structure

```text
CyclingTracker/
├── main.py
├── cyclingtracker.kv
├── buildozer.spec
├── cycling_tracker/
│   ├── permissions.py
│   ├── location.py
│   ├── ride_manager.py
│   ├── models/database.py
│   ├── ble/hr_monitor.py
│   ├── export/gpx.py
│   ├── services/controller.py
│   ├── services/ride_service.py
│   └── screens/
└── tests/
    ├── test_ble.py
    ├── test_database.py
    └── test_gpx.py
```

## Limitations

The Android-specific BLE and foreground-service code must still be validated
on an Android device. Host-side automated tests cover persistence, GPX
serialization, BLE measurement decoding, and service-side heart-rate
persistence, not device APIs or Android packaging.

## License

MIT
