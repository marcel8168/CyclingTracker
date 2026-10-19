"""Tests for Android-specific manifest build hooks."""

from xml.etree import ElementTree

from cycling_tracker.android_build import (
    ANDROID_NAMESPACE,
    SERVICE_NAME,
    patch_service_foreground_type,
)


def test_manifest_hook_sets_location_type_on_generated_service(tmp_path):
    manifest = tmp_path / 'AndroidManifest.xml'
    manifest.write_text(
        f'''<?xml version="1.0"?>
<manifest xmlns:android="{ANDROID_NAMESPACE}">
  <application>
    <service android:name="{SERVICE_NAME}" android:process=":service_Ride" />
  </application>
</manifest>
''',
        encoding='utf-8',
    )

    patch_service_foreground_type(manifest)

    root = ElementTree.parse(manifest).getroot()
    service = root.find('./application/service')
    assert service is not None
    assert service.get(f'{{{ANDROID_NAMESPACE}}}foregroundServiceType') == 'location'
    assert service.get(f'{{{ANDROID_NAMESPACE}}}exported') == 'false'
    assert service.get(f'{{{ANDROID_NAMESPACE}}}process') == ':service_Ride'
