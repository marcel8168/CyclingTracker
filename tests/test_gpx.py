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

    def test_rejects_invalid_coordinates(self):
        bad_samples = [dict(self.samples[0], latitude=91)]
        with self.assertRaises(ValueError):
            build_gpx(self.ride, bad_samples)

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
        ):
            result = publish_gpx(self.ride, self.samples)

        self.assertEqual(
            result, 'Download/CyclingTracker/CyclingTracker-ride-7.gpx'
        )
        values.put.assert_any_call('relative_path', 'Download/CyclingTracker')
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


if __name__ == '__main__':
    unittest.main()
