import logging
import threading
import time
from functools import partial


class TimerTask:

    def __init__(self, callable_, *args, **kwargs):
        self._callable = partial(callable_, *args, **kwargs)
        self._finished = False

    def is_finished(self):
        return self._finished

    def run(self):
        try:
            self._callable()
        # BaseException and not Exception: the Timer worker loop invokes jobs
        # without any outer guard, so anything escaping here kills the single
        # long lived thread and silently disables slow request tracing.
        # Under gevent (gevent.Timeout, GreenletExit) or a SystemExit raised
        # by a context injector this is a real occurrence.
        except BaseException:
            logging.exception('TimerTask failed')
        finally:
            self._finished = True


class Timer(threading.Thread):
    """An alternative to threading.Timer. Where threading.Timer spawns a
    dedicated thread for each job, this class uses a single, long-lived thread
    to process multiple jobs.

    Jobs are scheduled with a delay value in seconds.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.lock = threading.Condition()
        self._jobs = []
        self.die = False

    def run_later(self, callable_, timeout, *args, **kwargs):
        """Schedules the specified callable for delayed execution.

        Returns a TimerTask instance that can be used to cancel pending
        execution.
        """

        self.lock.acquire()
        try:
            if self.die:
                raise RuntimeError('This timer has been shut down and '
                                   'does not accept new jobs.')

            job = TimerTask(callable_, *args, **kwargs)
            self._jobs.append((job, time.time() + timeout))
            self._jobs.sort(key=lambda j: j[1])  # sort on time
            self.lock.notify()

            return job
        finally:
            self.lock.release()

    def cancel(self, timer_task):
        self.lock.acquire()
        try:
            self._jobs = list(filter(lambda job: job[0] is not timer_task,
                                     self._jobs))
            self.lock.notify()
        finally:
            self.lock.release()

    def shutdown(self, cancel_jobs=False):
        self.lock.acquire()
        try:
            self.die = True
            if cancel_jobs:
                self._jobs = []
            self.lock.notify()
        finally:
            self.lock.release()

    def _get_sleep_time(self):
        if not self._jobs:
            return 0
        else:
            job, scheduled_at = self._jobs[0]
            return scheduled_at - time.time()

    def run(self):
        while True:
            self.lock.acquire()
            job = None
            try:
                if not self._jobs:
                    if self.die:
                        break
                    else:
                        self.lock.wait()
                elif self._get_sleep_time() > 0:
                    self.lock.wait(self._get_sleep_time())
                else:
                    job, timeout = self._jobs.pop(0)
            finally:
                self.lock.release()

            if job:
                # invoke the task without holding the lock
                job.run()
