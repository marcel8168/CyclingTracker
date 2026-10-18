class Button:
    def __init__(self, *args, **kwargs):
        self.text = kwargs.get('text', '')
