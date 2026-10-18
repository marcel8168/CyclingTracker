class EventDispatcher:
    def __init__(self, **kwargs):
        self._property_callbacks = {}
        for key, value in kwargs.items():
            setattr(self, key, value)

    def bind(self, *args, **kwargs):
        for key, callback in kwargs.items():
            self._property_callbacks.setdefault(key, []).append(callback)
        for pair in args:
            if isinstance(pair, tuple) and len(pair) == 2:
                name, callback = pair
                self._property_callbacks.setdefault(name, []).append(callback)
