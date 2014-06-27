import datetime as dt
import os
import threading

from backlash.tbtools import get_current_traceback
from backlash.frtools import get_thread_stack, DumpThread
from backlash.utils import RequestContext
from .timer import Timer


class TraceSlowRequestsMiddleware(object):

    def __init__(self, app, reporters, context_injectors, interval=25,
                 exclude_paths=None):

        self.app = app
        self.reporters = reporters
        self.context_injectors = context_injectors
        self.interval = interval
        self.exclude_paths = exclude_paths or []

        self.timer = Timer()
        self.timer.setDaemon(True)
        self.timer.start()

    def _stream_response(self, environ, data):
        try:
            for chunk in data:
                yield chunk
        finally:
            if hasattr(data, 'close'):
                data.close()
            self._cancel_tracing(environ)

    def __call__(self, environ, start_response):
        try:
            self._start_tracing(environ)
            return self._stream_response(environ, self.app(environ, start_response))
        except Exception:
            self._cancel_tracing(environ)
            raise

    def peek(self, environ, thread_id, started):
        context = RequestContext({'environ': dict(environ)})
        for injector in self.context_injectors:
            context.update(injector(environ))

        context.update({
            'SLOW_REQUEST': {'ThreadID': thread_id,
                             'ProcessID': os.getpid(),
                             'Started': str(started)}
        })

        traceback = get_thread_stack(thread_id, environ.get('PATH_INFO', ''),
                                     context=context, error_type='SlowRequestError')
        for r in self.reporters:
            try:
                r.report(traceback)
            except Exception:
                error = get_current_traceback(skip=1, show_hidden_frames=False)
                environ['wsgi.errors'].write('\nError while reporting slow request with %s\n' % r)
                environ['wsgi.errors'].write(error.plaintext)

    @classmethod
    def _get_thread_id(cls):
        return threading.current_thread().ident

    def _is_exempt(self, environ):
        """
        Returns True if this request's URL starts with one of the
        excluded paths.
        """
        exemptions = self.exclude_paths

        if exemptions:
            path = environ.get('PATH_INFO')
            for excluded_p in self.exclude_paths:
                if path.startswith(excluded_p):
                    return True

        return False

    def _start_tracing(self, environ):
        if not self._is_exempt(environ):
            job = self.timer.run_later(self.peek,
                                       self.interval,
                                       environ,
                                       self._get_thread_id(),
                                       dt.datetime.utcnow())
            environ['BACKLASH_SLOW_TRACING_JOB'] = job

    def _cancel_tracing(self, environ):
        try:
            tracing_job = environ['BACKLASH_SLOW_TRACING_JOB']
            if tracing_job is not None:
                self.timer.cancel(tracing_job)
        except Exception:
            error = get_current_traceback(skip=1, show_hidden_frames=False)
            environ['wsgi.errors'].write('Failed to cancel slow requests tracing timer\n')
            environ['wsgi.errors'].write(error.plaintext)
