import threading
import time

class PeriodicTimer:
    """ Timer to call a target function periodically in the context of a separate thread. """
    def __init__(self, period, target=None, args=(), kwargs=None):
        self._period = float(period)
        self._target = target
        self._args = args
        if kwargs is None:
            kwargs = {}
        self._kwargs = kwargs
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._started = False

    def start(self):
        """ Start the timer. Must be called from the same thread as the stop method. """
        if self._started:
            # Timer has already been started.
            return
        if not self._thread.is_alive():
            self._thread.start()
        else:
            self._lock.release()
        self._started = True

    def stop(self):
        """ Stop the timer. """
        if not self._started:
            # Timer is not running.
            return
        self._lock.acquire()
        self._started = False

    def _run(self):
        """ The main loop of the timer thread. """
        while True:
            self._lock.acquire()
            self._lock.release()
            if self._target:
                self._target(*self._args, **self._kwargs)
            time.sleep(self._period)
