class Screen:
    def __init__(self, name=None, **kwargs):
        self.name = name
        self.manager = None


class ScreenManager:
    def __init__(self, **kwargs):
        self._screens = {}
        self.current = None

    def add_widget(self, screen):
        self._screens[screen.name] = screen
        screen.manager = self
        if self.current is None:
            self.current = screen.name

    def has_screen(self, name):
        return name in self._screens

    def get_screen(self, name):
        return self._screens[name]
