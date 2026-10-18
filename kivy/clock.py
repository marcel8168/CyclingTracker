import threading


class _TimerHandle:
    def __init__(self):
        self._thread = None
        self._running = True

    def cancel(self):
        self._running = False
        if self._thread is not None:
            self._thread.cancel()


class _Clock:
    @staticmethod
    def schedule_once(callback, timeout=0):
        if timeout == 0:
            callback(0)
            return _TimerHandle()
        timer = _TimerHandle()
        timer._thread = threading.Timer(timeout, lambda: callback(0))
        timer._thread.daemon = True
        timer._thread.start()
        return timer

    @staticmethod
    def schedule_interval(callback, timeout):
        timer = _TimerHandle()

        def runner():
            if not timer._running:
                return
            callback(0)
            timer._thread = threading.Timer(timeout, runner)
            timer._thread.daemon = True
            timer._thread.start()

        timer._thread = threading.Timer(timeout, runner)
        timer._thread.daemon = True
        timer._thread.start()
        return timer


Clock = _Clock()
