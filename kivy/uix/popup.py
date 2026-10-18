class Popup:
    def __init__(self, *args, **kwargs):
        self.title = kwargs.get('title', '')
        self.content = kwargs.get('content', None)
