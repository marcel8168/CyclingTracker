"""GPX 1.1 serialization and platform-specific ride export."""

import os
import xml.etree.ElementTree as ET
from datetime import datetime

GPX_NS = 'http://www.topografix.com/GPX/1/1'
GPXTPX_NS = 'http://www.garmin.com/xmlschemas/TrackPointExtension/v1'
ET.register_namespace('', GPX_NS)
ET.register_namespace('gpxtpx', GPXTPX_NS)


def _tag(namespace, name):
    return f'{{{namespace}}}{name}'


def _parse_time(value):
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('GPX timestamps must include a timezone')
    return parsed


def build_gpx(ride, samples, heart_rate_samples=()):
    """Return a GPX 1.1 document containing one recorded track."""
    root = ET.Element(_tag(GPX_NS, 'gpx'), {
        'version': '1.1',
        'creator': 'CyclingTracker',
    })
    metadata = ET.SubElement(root, _tag(GPX_NS, 'metadata'))
    started = _parse_time(ride['started_at'])
    ET.SubElement(metadata, _tag(GPX_NS, 'time')).text = (
        started.isoformat().replace('+00:00', 'Z')
    )
    track = ET.SubElement(root, _tag(GPX_NS, 'trk'))
    ET.SubElement(track, _tag(GPX_NS, 'name')).text = (
        f'CyclingTracker ride {ride["id"]}'
    )
    segment = ET.SubElement(track, _tag(GPX_NS, 'trkseg'))

    timed_hr = [
        (_parse_time(sample['timestamp']), int(sample['heart_rate']))
        for sample in heart_rate_samples
    ]
    hr_index = 0
    for sample in samples:
        latitude = float(sample['latitude'])
        longitude = float(sample['longitude'])
        if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
            raise ValueError('Ride contains an invalid GPS coordinate')
        point = ET.SubElement(segment, _tag(GPX_NS, 'trkpt'), {
            'lat': f'{latitude:.7f}',
            'lon': f'{longitude:.7f}',
        })
        if sample['altitude'] is not None:
            ET.SubElement(point, _tag(GPX_NS, 'ele')).text = (
                f'{float(sample["altitude"]):.2f}'
            )
        sample_time = _parse_time(sample['timestamp'])
        ET.SubElement(point, _tag(GPX_NS, 'time')).text = (
            sample_time.isoformat().replace('+00:00', 'Z')
        )
        bpm = sample['heart_rate']
        if bpm is None and timed_hr:
            while (
                hr_index + 1 < len(timed_hr)
                and abs((timed_hr[hr_index + 1][0] - sample_time).total_seconds())
                < abs((timed_hr[hr_index][0] - sample_time).total_seconds())
            ):
                hr_index += 1
            closest_time, closest_bpm = timed_hr[hr_index]
            if abs((closest_time - sample_time).total_seconds()) <= 5:
                bpm = closest_bpm
        if bpm is not None:
            if not 1 <= int(bpm) <= 255:
                raise ValueError('Ride contains an invalid heart-rate value')
            extensions = ET.SubElement(point, _tag(GPX_NS, 'extensions'))
            track_point = ET.SubElement(
                extensions, _tag(GPXTPX_NS, 'TrackPointExtension')
            )
            ET.SubElement(track_point, _tag(GPXTPX_NS, 'hr')).text = str(int(bpm))

    return ET.tostring(root, encoding='utf-8', xml_declaration=True)


def export_gpx(ride, samples, heart_rate_samples=(), path=None):
    """Write a GPX file and return its absolute path."""
    document = build_gpx(ride, samples, heart_rate_samples)
    if path is None:
        from kivy.app import App
        path = os.path.join(
            App.get_running_app().user_data_dir,
            'exports',
            f'ride-{ride["id"]}.gpx'
        )
    path = os.path.abspath(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as output:
        output.write(document)
    return path


def _signed_byte_chunks(document, chunk_size=64 * 1024):
    """Yield signed-byte chunks for Android OutputStream writes."""
    for offset in range(0, len(document), chunk_size):
        chunk = document[offset:offset + chunk_size]
        yield [byte if byte < 128 else byte - 256 for byte in chunk]


def publish_gpx(ride, samples, heart_rate_samples=(), app=None):
    """Export GPX to Android Downloads where supported, otherwise app storage."""
    from kivy.utils import platform

    if platform != 'android':
        return export_gpx(ride, samples, heart_rate_samples)

    document = build_gpx(ride, samples, heart_rate_samples)
    from jnius import Array, autoclass

    PythonActivity = autoclass('org.kivy.android.PythonActivity')
    context = app or PythonActivity.mActivity
    BuildVersion = autoclass('android.os.Build$VERSION')
    filename = f'CyclingTracker-ride-{ride["id"]}.gpx'
    if BuildVersion.SDK_INT >= 29:
        ContentValues = autoclass('android.content.ContentValues')
        MediaStoreDownloads = autoclass('android.provider.MediaStore$Downloads')
        values = ContentValues()
        values.put('display_name', filename)
        values.put('mime_type', 'application/gpx+xml')
        values.put('relative_path', 'Download/CyclingTracker')
        resolver = context.getContentResolver()
        uri = resolver.insert(MediaStoreDownloads.EXTERNAL_CONTENT_URI, values)
        if uri is None:
            raise OSError('Android could not create the GPX file in Downloads')
        stream = resolver.openOutputStream(uri)
        if stream is None:
            raise OSError('Android could not open the exported GPX file')
        try:
            for signed_chunk in _signed_byte_chunks(document):
                stream.write(Array('b', signed_chunk))
            stream.flush()
        finally:
            stream.close()
        return f'Download/CyclingTracker/{filename}'

    directory = context.getExternalFilesDir('Documents')
    if directory is None:
        raise OSError('Android documents storage is unavailable')
    path = os.path.join(directory.getAbsolutePath(), filename)
    with open(path, 'wb') as output:
        output.write(document)
    return path
