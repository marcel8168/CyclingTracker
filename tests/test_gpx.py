"""Tests for GPX serialization."""

import unittest
import xml.etree.ElementTree as ET

from cycling_tracker.export.gpx import GPX_NS, GPXTPX_NS, build_gpx


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


if __name__ == '__main__':
    unittest.main()
