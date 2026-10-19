"""Tests for GPX serialization."""

import os
import sys
import tempfile
import types
import unittest
import xml.etree.ElementTree as ET
from unittest import mock

from cycling_tracker.export.gpx import (
    GPX_NS,
    GPXTPX_NS,
    _signed_byte_chunks,
    build_gpx,
    publish_gpx,
)


class GpxTests(unittest.TestCase):
    def setUp(self):
        self.ride = {
            'id': 7,
            'started_at': '2026-10-17T10:00:00+00:00',
        }
        self.samples = [{
            'latitude': 51.5,
            'longitude': -0.12,
            'altitude': 15.25,
            'timestamp': '2026-10-17T10:00:01+00:00',
            'heart_rate': None,
        }]

    def test_exports_valid_track_with_nearest_heart_rate(self):
        heart_rate_samples = [{
            'timestamp': '2026-10-17T10:00:02+00:00',
            'heart_rate': 142,
        }]

        document = build_gpx(self.ride, self.samples, heart_rate_samples)
        root = ET.fromstring(document)
        point = root.find(f'.//{{{GPX_NS}}}trkpt')

        self.assertEqual(root.attrib['version'], '1.1')
        self.assertEqual(point.attrib['lat'], '51.5000000')
        self.assertEqual(
            point.find(
                f'{{{GPX_NS}}}extensions/{{{GPXTPX_NS}}}TrackPointExtension/'
                f'{{{GPXTPX_NS}}}hr'
            ).text,
            '142',
        )

    def test_skips_invalid_coordinates_and_exports_remaining_samples(self):
        samples = [
            dict(self.samples[0], latitude=91),
            dict(self.samples[0], latitude=float('nan')),
            dict(self.samples[0], timestamp='2026-10-17T10:00:02+00:00'),
        ]

        with mock.patch('cycling_tracker.export.gpx.Logger.warning') as warning:
            root = ET.fromstring(build_gpx(self.ride, samples))

        points = root.findall(f'.//{{{GPX_NS}}}trkpt')
        self.assertEqual(len(points), 1)
        self.assertEqual(points[0].attrib['lat'], '51.5000000')
        self.assertEqual(warning.call_count, 2)

    def test_omits_invalid_sample_and_timed_heart_rates(self):
        samples = [
            dict(self.samples[0], heart_rate=300),
            dict(self.samples[0], timestamp='2026-10-17T10:00:02+00:00'),
        ]
        heart_rate_samples = [{
            'timestamp': '2026-10-17T10:00:02+00:00',
            'heart_rate': 0,
        }]

        with mock.patch('cycling_tracker.export.gpx.Logger.warning') as warning:
            root = ET.fromstring(
                build_gpx(self.ride, samples, heart_rate_samples)
            )

        points = root.findall(f'.//{{{GPX_NS}}}trkpt')
        self.assertEqual(len(points), 2)
        self.assertTrue(all(
            point.find(f'{{{GPX_NS}}}extensions') is None
            for point in points
        ))
        self.assertEqual(warning.call_count, 2)

    def test_rejects_timestamp_without_timezone(self):
        bad_samples = [dict(self.samples[0], timestamp='2026-10-17T10:00:01')]
        with self.assertRaises(ValueError):
            build_gpx(self.ride, bad_samples)

    def test_signed_byte_chunks_convert_utf8_document_without_materializing_list(self):
        document = b'\x00\x7f\x80\xff'
        chunks = list(_signed_byte_chunks(document, chunk_size=2))

        self.assertEqual(chunks, [[0, 127], [-128, -1]])

    def test_android_10_export_is_published_to_downloads(self):
        context = mock.Mock()
        resolver = context.getContentResolver.return_value
        resolver.insert.return_value = 'content://downloads/ride-7'
        stream = resolver.openOutputStream.return_value
        values = mock.Mock()
        published_values = mock.Mock()
        content_values = mock.Mock(side_effect=[values, published_values])
        resolver.update.return_value = 1
        downloads = types.SimpleNamespace(EXTERNAL_CONTENT_URI='downloads-uri')
        classes = {
            'org.kivy.android.PythonActivity':
                types.SimpleNamespace(mActivity=context),
            'android.os.Build$VERSION': types.SimpleNamespace(SDK_INT=29),
            'android.content.ContentValues': content_values,
            'android.provider.MediaStore$Downloads': downloads,
        }
        java_module = types.ModuleType('jnius')
        java_module.Array = lambda _type, data: bytes(
            byte if byte >= 0 else byte + 256 for byte in data
        )
        java_module.autoclass = lambda name: classes[name]

        with (
            mock.patch('kivy.utils.platform', 'android'),
            mock.patch.dict(sys.modules, {'jnius': java_module}),
        ):
            result = publish_gpx(self.ride, self.samples)

        self.assertEqual(
            result, 'Download/CyclingTracker/CyclingTracker-ride-7.gpx'
        )
        values.put.assert_any_call(
            '_display_name', 'CyclingTracker-ride-7.gpx'
        )
        values.put.assert_any_call('relative_path', 'Download/CyclingTracker')
        values.put.assert_any_call('is_pending', 1)
        resolver.insert.assert_called_once_with('downloads-uri', values)
        resolver.openOutputStream.assert_called_once_with(
            'content://downloads/ride-7'
        )
        self.assertEqual(
            b''.join(call.args[0] for call in stream.write.call_args_list),
            build_gpx(self.ride, self.samples),
        )
        stream.flush.assert_called_once()
        stream.close.assert_called_once()
        resolver.update.assert_called_once()
        published_values.put.assert_called_once_with('is_pending', 0)
        resolver.delete.assert_not_called()

    def test_android_export_deletes_entry_when_output_stream_cannot_be_opened(self):
        context = mock.Mock()
        resolver = context.getContentResolver.return_value
        resolver.insert.return_value = 'content://downloads/ride-7'
        resolver.openOutputStream.return_value = None
        values = mock.Mock()
        downloads = types.SimpleNamespace(EXTERNAL_CONTENT_URI='downloads-uri')
        classes = {
            'org.kivy.android.PythonActivity':
                types.SimpleNamespace(mActivity=context),
            'android.os.Build$VERSION': types.SimpleNamespace(SDK_INT=29),
            'android.content.ContentValues': mock.Mock(return_value=values),
            'android.provider.MediaStore$Downloads': downloads,
        }
        java_module = types.ModuleType('jnius')
        java_module.Array = lambda _type, data: bytes(
            byte if byte >= 0 else byte + 256 for byte in data
        )
        java_module.autoclass = lambda name: classes[name]

        with (
            mock.patch('kivy.utils.platform', 'android'),
            mock.patch.dict(sys.modules, {'jnius': java_module}),
            self.assertRaisesRegex(OSError, 'could not open'),
        ):
            publish_gpx(self.ride, self.samples)

        resolver.delete.assert_called_once_with(
            'content://downloads/ride-7', None, None
        )
        resolver.update.assert_not_called()

    def test_android_export_deletes_entry_when_write_fails(self):
        context = mock.Mock()
        resolver = context.getContentResolver.return_value
        resolver.insert.return_value = 'content://downloads/ride-7'
        stream = resolver.openOutputStream.return_value
        stream.write.side_effect = OSError('disk full')
        values = mock.Mock()
        downloads = types.SimpleNamespace(EXTERNAL_CONTENT_URI='downloads-uri')
        classes = {
            'org.kivy.android.PythonActivity':
                types.SimpleNamespace(mActivity=context),
            'android.os.Build$VERSION': types.SimpleNamespace(SDK_INT=29),
            'android.content.ContentValues': mock.Mock(return_value=values),
            'android.provider.MediaStore$Downloads': downloads,
        }
        java_module = types.ModuleType('jnius')
        java_module.Array = lambda _type, data: bytes(
            byte if byte >= 0 else byte + 256 for byte in data
        )
        java_module.autoclass = lambda name: classes[name]

        with (
            mock.patch('kivy.utils.platform', 'android'),
            mock.patch.dict(sys.modules, {'jnius': java_module}),
            self.assertRaisesRegex(OSError, 'disk full'),
        ):
            publish_gpx(self.ride, self.samples)

        stream.close.assert_called_once()
        resolver.delete.assert_called_once_with(
            'content://downloads/ride-7', None, None
        )
        resolver.update.assert_not_called()

    def test_android_export_deletes_entry_when_publish_update_fails(self):
        context = mock.Mock()
        resolver = context.getContentResolver.return_value
        resolver.insert.return_value = 'content://downloads/ride-7'
        resolver.update.return_value = 0
        values = mock.Mock()
        downloads = types.SimpleNamespace(EXTERNAL_CONTENT_URI='downloads-uri')
        classes = {
            'org.kivy.android.PythonActivity':
                types.SimpleNamespace(mActivity=context),
            'android.os.Build$VERSION': types.SimpleNamespace(SDK_INT=29),
            'android.content.ContentValues': mock.Mock(return_value=values),
            'android.provider.MediaStore$Downloads': downloads,
        }
        java_module = types.ModuleType('jnius')
        java_module.Array = lambda _type, data: bytes(
            byte if byte >= 0 else byte + 256 for byte in data
        )
        java_module.autoclass = lambda name: classes[name]

        with (
            mock.patch('kivy.utils.platform', 'android'),
            mock.patch.dict(sys.modules, {'jnius': java_module}),
            self.assertRaisesRegex(OSError, 'could not publish'),
        ):
            publish_gpx(self.ride, self.samples)

        resolver.delete.assert_called_once_with(
            'content://downloads/ride-7', None, None
        )


if __name__ == '__main__':
    unittest.main()
