"""Ride history and GPX export screen."""

from datetime import datetime

from kivy.app import App
from kivy.logger import Logger
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.screenmanager import Screen

from cycling_tracker.export.gpx import publish_gpx


class HistoryScreen(Screen):
    """List saved rides and export their GPX tracks."""

    def on_enter(self):
        self.refresh()

    def refresh(self):
        container = self.ids.get('ride_list')
        if container is None:
            return
        container.clear_widgets()
        manager = App.get_running_app().ride_manager
        if manager.db._conn is None:
            manager.db.open()
        rides = manager.db.list_rides()
        if not rides:
            container.add_widget(Label(
                text='No completed rides yet.',
                size_hint_y=None,
                height=dp(48)
            ))
            return
        for ride in rides:
            started = datetime.fromisoformat(ride['started_at']).astimezone()
            elapsed = int(ride['total_elapsed_s'] or 0)
            hours, rem = divmod(elapsed, 3600)
            minutes, seconds = divmod(rem, 60)
            summary = (
                f'{started:%Y-%m-%d %H:%M}  |  '
                f'{ride["total_distance_m"] / 1000:.2f} km  |  '
                f'{hours:02d}:{minutes:02d}:{seconds:02d}'
            )
            row = BoxLayout(
                orientation='vertical',
                size_hint_y=None,
                height=dp(96),
                spacing=dp(4),
                padding=dp(4),
            )
            row.add_widget(Label(
                text=summary,
                size_hint_y=None,
                height=dp(36),
                halign='left',
                valign='middle',
                text_size=(self.width, None)
            ))
            export_button = Button(
                text='Export GPX',
                size_hint_y=None,
                height=dp(44)
            )
            export_button.bind(
                on_release=lambda _button, ride_id=ride['id']:
                self.export_ride(ride_id)
            )
            row.add_widget(export_button)
            container.add_widget(row)

    def export_ride(self, ride_id):
        manager = App.get_running_app().ride_manager
        try:
            ride = manager.db.get_ride(ride_id)
            if ride is None:
                raise ValueError(f'Ride {ride_id} no longer exists')
            path = publish_gpx(
                ride,
                manager.db.get_samples(ride_id),
                manager.db.get_heart_rate_samples(ride_id),
            )
            self._show_message('GPX exported', path)
        except (OSError, ValueError, RuntimeError) as exc:
            Logger.exception(f'HistoryScreen: GPX export failed: {exc}')
            self._show_message('Export failed', str(exc))
        except Exception as exc:
            Logger.exception(f'HistoryScreen: unexpected GPX export error: {exc}')
            self._show_message('Export failed', str(exc))

    @staticmethod
    def _show_message(title, message):
        Popup(
            title=title,
            content=Label(text=message, halign='center'),
            size_hint=(0.85, 0.35),
            auto_dismiss=True,
        ).open()
