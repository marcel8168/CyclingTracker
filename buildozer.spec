[app]

# (str) Title of your application
title = CyclingTracker

# (str) Package name
package.name = cyclingtracker

# (str) Package domain (needed for android/ios packaging)
package.domain = org.cyclingtracker

# (str) Source code directory where main.py lives
source.dir = .

# (list) Source files to include (let empty to include all)
source.include_exts = py,png,jpg,kv,atlas,json

# Keep the local Kivy test doubles from shadowing the packaged Kivy runtime.
source.exclude_dirs = kivy

# (str) Application versioning
version = 0.1.0

# (list) Application requirements
requirements = python3,kivy==2.3.0,pyjnius,android,plyer

# (str) Pin python-for-android to a Python 3.11 release compatible with Kivy 2.3.0
p4a.branch = master
p4a.commit = 957a3e5f8c270f7aa648ba185e5a68c1077a798d

# (str) Presplash of the application (an image displayed during loading)
#presplash.filename = %(source.dir)s/data/presplash.png

# (str) Icon of the application
#icon.filename = %(source.dir)s/data/icon.png

# (str) Supported orientation
orientation = portrait

# (bool) Indicate if the application should be fullscreen or not
fullscreen = 0

#
# Android specific
#

# (list) Permissions
android.permissions = ACCESS_FINE_LOCATION,ACCESS_COARSE_LOCATION,ACCESS_BACKGROUND_LOCATION,BLUETOOTH,BLUETOOTH_ADMIN,BLUETOOTH_SCAN,BLUETOOTH_CONNECT,FOREGROUND_SERVICE,FOREGROUND_SERVICE_LOCATION,POST_NOTIFICATIONS,WAKE_LOCK

# (int) Target Android API
android.api = 34

# (int) Minimum API
android.minapi = 26

# (str) Android NDK version to use
android.ndk = 25b

# (bool) Use --hierarchical-architecture for android packaging
# android.archs = arm64-v8a
android.archs = arm64-v8a,armeabi-v7a

# (list) Android additional libraries (AAR / JAR)
#android.add_aars =

# (list) Android additional Java classes to include
android.add_src = %(source.dir)s/android/src

# (bool) Enable AndroidX support
android.enable_androidx = True

# (list) Gradle dependencies
#android.gradle_dependencies =

# (str) The Android entry point — needed for services
android.entrypoint = org.kivy.android.PythonActivity

# (list) Android services
# Format: name:entrypoint_python_file[:foreground][:sticky]
# Start as a foreground service so Android keeps the GPS/BLE recorder alive.
services = Ride:cycling_tracker/services/ride_service.py:sticky
p4a.hook = %(source.dir)s/cycling_tracker/android_build.py

# (str) Android logcat filters to use
android.logcat_filters = *:S python:D AndroidRuntime:E ActivityManager:W BluetoothGatt:E BluetoothLeScanner:E CyclingTrackerGattCallback:I

# (bool) Copy library instead of making a libpymodules.so
# android.copy_libs = 1

# (str) The format used to package the app for release
# android.release_artifact = aab

# (str) The format used to package the app for debug
# android.debug_artifact = apk

#
# iOS specific (not used)
#

[buildozer]

# (int) Log level (0 = error only, 1 = info, 2 = debug with command output)
log_level = 2

# (int) Display warning if buildozer is run as root (0 = False, 1 = True)
warn_on_root = 1
