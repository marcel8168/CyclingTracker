"""BLE heart-rate sensor settings."""

from kivy.app import App
from kivy.metrics import dp
from kivy.properties import StringProperty
from kivy.uix.button import Button
from kivy.uix.screenmanager import Screen


class SettingsScreen(Screen):
    """Discover and select a standard BLE heart-rate sensor."""

    status_text = StringProperty('Disconnected')

    def on_enter(self):
        self.status_text = App.get_running_app().ble_status

    def scan(self):
        app = App.get_running_app()
        if not app.permission_manager.can_use_ble:
            self.status_text = 'Bluetooth permission is required'
            return
        if app.heart_rate_monitor is None:
            self.status_text = 'Heart-rate monitor is unavailable'
            return
        self.ids.device_list.clear_widgets()
        self.status_text = 'Scanning…'
        app.heart_rate_monitor.scan()

    def show_devices(self, devices):
        device_list = self.ids.get('device_list')
        if device_list is None:
            return
        device_list.clear_widgets()
        for device in devices:
            button = Button(
                text=f'{device["name"]}  ({device["address"]})',
                size_hint_y=None,
                height=dp(48),
            )
            button.bind(
                on_release=lambda _button, address=device['address']:
                self.connect_device(address)
            )
            device_list.add_widget(button)

    def connect_device(self, address):
        app = App.get_running_app()
        monitor = app.heart_rate_monitor
        if monitor is not None:
            db = app.ride_manager.db
            if db._conn is None:
                db.open()
            if monitor.connect(address):
                db.set_setting('ble_device_address', address)

    def disconnect_device(self):
        monitor = App.get_running_app().heart_rate_monitor
        if monitor is not None:
            monitor.disconnect()
