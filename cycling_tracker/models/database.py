"""
SQLite database manager for CyclingTracker.

Provides a single connection per process with WAL mode for
concurrent read/write safety. Samples are committed immediately
so an interrupted process never discards ride data.
"""

import os
import sqlite3
import logging
import sys
from datetime import datetime, timezone

try:
    from kivy.logger import Logger
    from kivy.utils import platform
except ModuleNotFoundError:
    Logger = logging.getLogger('cycling_tracker.database')
    platform = 'android' if sys.platform == 'android' else sys.platform


def _default_db_path():
    """Return the platform-appropriate database file path."""
    if platform == 'android':
        # Android app-private storage
        from jnius import autoclass
        try:
            PythonActivity = autoclass('org.kivy.android.PythonActivity')
            context = PythonActivity.mActivity
            if context is None:
                raise RuntimeError('activity context unavailable in service')
        except Exception:
            PythonService = autoclass('org.kivy.android.PythonService')
            context = PythonService.mService
        if context is None:
            raise RuntimeError('Android app/service context is unavailable')
        db_dir = context.getFilesDir().getAbsolutePath()
    else:
        # Desktop: store next to the app in an owner-only directory.
        db_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__)
            ))),
            'data'
        )
        os.makedirs(db_dir, mode=0o700, exist_ok=True)
        if os.name == 'posix':
            os.chmod(db_dir, 0o700)
    os.makedirs(db_dir, exist_ok=True)
    return os.path.join(db_dir, 'cyclingtracker.db')


_SCHEMA_VERSION = 3

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS rides (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at      TEXT    NOT NULL,
    ended_at        TEXT,
    status          TEXT    NOT NULL DEFAULT 'active',
    total_distance_m REAL   NOT NULL DEFAULT 0.0,
    total_elapsed_s INTEGER NOT NULL DEFAULT 0,
    notes           TEXT
);

CREATE TABLE IF NOT EXISTS samples (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ride_id     INTEGER NOT NULL,
    timestamp   TEXT    NOT NULL,
    latitude    REAL    NOT NULL,
    longitude   REAL    NOT NULL,
    altitude    REAL,
    speed       REAL,
    bearing     REAL,
    accuracy    REAL,
    heart_rate  INTEGER,
    source      TEXT    NOT NULL DEFAULT 'gps',
    FOREIGN KEY (ride_id) REFERENCES rides(id)
);

CREATE INDEX IF NOT EXISTS idx_samples_ride_id
    ON samples(ride_id);

CREATE INDEX IF NOT EXISTS idx_samples_timestamp
    ON samples(ride_id, timestamp);

CREATE TABLE IF NOT EXISTS heart_rate_samples (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ride_id     INTEGER NOT NULL,
    timestamp   TEXT    NOT NULL,
    heart_rate  INTEGER NOT NULL,
    FOREIGN KEY (ride_id) REFERENCES rides(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_hr_ride_timestamp
    ON heart_rate_samples(ride_id, timestamp);

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS app_settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class Database:
    """SQLite database manager.

    Usage::

        db = Database()          # or Database('/path/to/db')
        db.open()
        ride_id = db.create_ride()
        db.insert_sample(ride_id, ...)
        db.close()
    """

    def __init__(self, db_path=None):
        self.db_path = db_path or _default_db_path()
        self._conn = None

    def open(self):
        """Open the database and ensure the schema exists."""
        Logger.info(f'Database: opening {self.db_path}')
        if os.name == 'posix':
            descriptor = os.open(
                self.db_path, os.O_CREAT | os.O_RDWR, 0o600
            )
            try:
                os.fchmod(descriptor, 0o600)
            finally:
                os.close(descriptor)
        self._conn = sqlite3.connect(self.db_path, timeout=10.0)
        self._conn.row_factory = sqlite3.Row
        # WAL mode: readers don't block writers, but separate processes still
        # need a timeout to avoid the UI/service process deadlocking on each
        # other while one connection has an in-flight write transaction.
        self._conn.execute('PRAGMA journal_mode=WAL')
        self._conn.execute('PRAGMA foreign_keys=ON')
        self._conn.execute('PRAGMA busy_timeout = 10000')
        self._init_schema()

    def close(self):
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None
            Logger.info('Database: closed')

    @property
    def conn(self):
        if self._conn is None:
            raise RuntimeError('Database is not open')
        return self._conn

    def _init_schema(self):
        """Create tables if they don't exist."""
        self.conn.executescript(_SCHEMA_SQL)
        # Track schema version
        row = self.conn.execute(
            'SELECT version FROM schema_version LIMIT 1'
        ).fetchone()
        if row is None:
            self.conn.execute(
                'INSERT INTO schema_version (version) VALUES (?)',
                (_SCHEMA_VERSION,)
            )
            self.conn.commit()
        elif row['version'] < _SCHEMA_VERSION:
            self.conn.execute(
                'UPDATE schema_version SET version = ?',
                (_SCHEMA_VERSION,)
            )
            self.conn.commit()
        Logger.info(f'Database: schema version {_SCHEMA_VERSION}')

    # ── Ride operations ──────────────────────────────────────────

    def create_ride(self):
        """Create a new active ride and return its id."""
        now = datetime.now(timezone.utc).isoformat()
        cursor = self.conn.execute(
            'INSERT INTO rides (started_at, status) VALUES (?, ?)',
            (now, 'active')
        )
        self.conn.commit()
        ride_id = cursor.lastrowid
        Logger.info(f'Database: created ride {ride_id}')
        return ride_id

    def finish_ride(self, ride_id, total_distance_m, total_elapsed_s):
        """Mark a ride as completed."""
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            '''UPDATE rides
               SET ended_at = ?, status = 'completed',
                   total_distance_m = ?, total_elapsed_s = ?
               WHERE id = ?''',
            (now, total_distance_m, total_elapsed_s, ride_id)
        )
        self.conn.commit()
        Logger.info(f'Database: finished ride {ride_id}')

    def discard_ride(self, ride_id):
        """Delete a ride and all its samples (e.g. user cancellation)."""
        self.conn.execute(
            'DELETE FROM heart_rate_samples WHERE ride_id = ?', (ride_id,)
        )
        self.conn.execute('DELETE FROM samples WHERE ride_id = ?', (ride_id,))
        self.conn.execute('DELETE FROM rides WHERE id = ?', (ride_id,))
        self.conn.commit()
        Logger.info(f'Database: discarded ride {ride_id}')

    def get_ride(self, ride_id):
        """Return a ride row or None."""
        return self.conn.execute(
            'SELECT * FROM rides WHERE id = ?', (ride_id,)
        ).fetchone()

    def get_active_ride(self):
        """Return the most recent active ride, or None."""
        return self.conn.execute(
            "SELECT * FROM rides WHERE status = 'active' ORDER BY id DESC LIMIT 1"
        ).fetchone()

    def set_setting(self, key, value):
        """Persist an application setting shared by the UI and service."""
        self.conn.execute(
            '''INSERT INTO app_settings (key, value) VALUES (?, ?)
               ON CONFLICT(key) DO UPDATE SET value = excluded.value''',
            (key, value)
        )
        self.conn.commit()

    def get_setting(self, key, default=None):
        """Return an application setting, or its default when unset."""
        row = self.conn.execute(
            'SELECT value FROM app_settings WHERE key = ?', (key,)
        ).fetchone()
        return row['value'] if row else default

    def list_rides(self, limit=50, offset=0):
        """Return completed rides, newest first."""
        return self.conn.execute(
            '''SELECT * FROM rides
               WHERE status = 'completed'
               ORDER BY started_at DESC
               LIMIT ? OFFSET ?''',
            (limit, offset)
        ).fetchall()

    def update_ride_distance(self, ride_id, total_distance_m):
        """Update the running distance total for a ride."""
        self.conn.execute(
            'UPDATE rides SET total_distance_m = ? WHERE id = ?',
            (total_distance_m, ride_id)
        )
        self.conn.commit()

    def update_ride_elapsed(self, ride_id, total_elapsed_s):
        """Update the running elapsed time for a ride."""
        with self.conn:
            self.conn.execute(
                'UPDATE rides SET total_elapsed_s = ? WHERE id = ?',
                (total_elapsed_s, ride_id)
            )

    # ── Sample operations ────────────────────────────────────────

    def insert_sample(self, ride_id, latitude, longitude, altitude=None,
                      speed=None, bearing=None, accuracy=None,
                      heart_rate=None, source='gps', timestamp=None):
        """Insert a location/sensor sample and commit immediately.

        Immediate commit ensures no data is lost if the process is
        killed unexpectedly.
        """
        now = timestamp or datetime.now(timezone.utc).isoformat()
        cursor = self.conn.execute(
            '''INSERT INTO samples
               (ride_id, timestamp, latitude, longitude, altitude,
                speed, bearing, accuracy, heart_rate, source)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (ride_id, now, latitude, longitude, altitude,
             speed, bearing, accuracy, heart_rate, source)
        )
        self.conn.commit()
        return cursor.lastrowid

    def insert_heart_rate(self, ride_id, heart_rate, timestamp=None):
        """Persist a heart-rate measurement independently of GPS sampling."""
        if not 1 <= int(heart_rate) <= 255:
            raise ValueError('heart_rate must be between 1 and 255 bpm')
        measured_at = timestamp or datetime.now(timezone.utc).isoformat()
        cursor = self.conn.execute(
            '''INSERT INTO heart_rate_samples (ride_id, timestamp, heart_rate)
               VALUES (?, ?, ?)''',
            (ride_id, measured_at, int(heart_rate))
        )
        self.conn.commit()
        return cursor.lastrowid

    def get_heart_rate_samples(self, ride_id):
        """Return heart-rate measurements for a ride in timestamp order."""
        return self.conn.execute(
            '''SELECT * FROM heart_rate_samples
               WHERE ride_id = ? ORDER BY timestamp''',
            (ride_id,)
        ).fetchall()

    def get_samples(self, ride_id):
        """Return all samples for a ride, ordered by timestamp."""
        return self.conn.execute(
            'SELECT * FROM samples WHERE ride_id = ? ORDER BY timestamp',
            (ride_id,)
        ).fetchall()

    def get_sample_count(self, ride_id):
        """Return the number of samples for a ride."""
        row = self.conn.execute(
            'SELECT COUNT(*) as cnt FROM samples WHERE ride_id = ?',
            (ride_id,)
        ).fetchone()
        return row['cnt'] if row else 0

    def get_last_sample(self, ride_id):
        """Return the most recent location sample, or None."""
        return self.conn.execute(
            '''SELECT * FROM samples WHERE ride_id = ?
               ORDER BY timestamp DESC, id DESC LIMIT 1''',
            (ride_id,)
        ).fetchone()

    def delete_ride(self, ride_id):
        """Delete a ride and all its samples."""
        self.conn.execute(
            'DELETE FROM heart_rate_samples WHERE ride_id = ?', (ride_id,)
        )
        self.conn.execute('DELETE FROM samples WHERE ride_id = ?', (ride_id,))
        self.conn.execute('DELETE FROM rides WHERE id = ?', (ride_id,))
        self.conn.commit()
        Logger.info(f'Database: deleted ride {ride_id}')
