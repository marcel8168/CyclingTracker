class _Property:
    def __init__(self, default=None):
        self.default = default
        self.name = None

    def __set_name__(self, owner, name):
        self.name = name

    def __get__(self, instance, owner=None):
        if instance is None:
            return self
        return instance.__dict__.get(self.name, self.default)

    def __set__(self, instance, value):
        if instance is None:
            raise AttributeError('Cannot set property on class')
        instance.__dict__[self.name] = value
        for callback in instance._property_callbacks.get(self.name, ()):  # pragma: no cover
            callback(instance, value)

class NumericProperty(_Property):
    pass

class BooleanProperty(_Property):
    pass

class StringProperty(_Property):
    pass

class ObjectProperty(_Property):
    def __init__(self, default=None, allownone=False):
        super().__init__(default)
