"""
Dashboard screen — landing page showing permission/sensor status
and navigation to ride, history, and settings screens.
"""

from kivy.uix.screenmanager import Screen
from kivy.logger import Logger


class DashboardScreen(Screen):
    """Main dashboard with status overview and navigation."""

    def on_enter(self):
        """Refresh status indicators when the screen is displayed."""
        Logger.info('DashboardScreen: on_enter')
