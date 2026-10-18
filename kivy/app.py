import os

from kivy.event import EventDispatcher


class App(EventDispatcher):
    _running_app = None

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.user_data_dir = os.path.join(os.getcwd(), '.kivy-data')
        App._running_app = self

    @classmethod
    def get_running_app(cls):
        return cls._running_app

    def build(self):
        return None

    def run(self):
        return None
