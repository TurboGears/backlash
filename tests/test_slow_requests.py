"""Behavioral tests for the WSGI slow requests tracing middleware.

Covers the stack snapshot handed to the reporters when a request outlives the
interval, excluded paths, cancellation of the pending trace once the response
is consumed, and the underlying single threaded Timer.
"""
import io
import time

from backlash import TraceSlowRequestsMiddleware
from backlash.tracing.slowrequests.timer import Timer


class RecordingReporter(object):
    def __init__(self):
        self.tracebacks = []

    def report(self, traceback):
        self.tracebacks.append(traceback)


def ok_app(environ, start_response):
    start_response('200 OK', [('Content-Type', 'text/plain')])
    return [b'app-response']


def wsgi_environ(path='/'):
    """Minimal WSGI environ, as a real server would provide it."""
    return {
        'REQUEST_METHOD': 'GET',
        'PATH_INFO': path,
        'QUERY_STRING': '',
        'SERVER_NAME': 'localhost',
        'SERVER_PORT': '80',
        'wsgi.url_scheme': 'http',
        'wsgi.errors': io.StringIO(),
    }


def run_wsgi(app, environ):
    """Drive the app in-process to completion: returns (status, body)."""
    captured = {}

    def start_response(status, headers, exc_info=None):
        captured['status'] = status

    body = b''.join(app(environ, start_response))
    return captured.get('status'), body


def wait_for(condition, timeout=2.0):
    """Poll until the timer thread did its job, without pinning any duration."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if condition():
            return True
        time.sleep(0.005)
    return False


def test_slow_request_is_reported_with_the_running_stack():
    reporter = RecordingReporter()
    app = TraceSlowRequestsMiddleware(ok_app, [reporter],
                                      [lambda environ: {'marker': 'injected'}],
                                      interval=0)
    try:
        environ = wsgi_environ('/slow')
        # the response is left unconsumed so the trace is not cancelled
        app_iter = app(environ, lambda status, headers: None)
        assert wait_for(lambda: reporter.tracebacks)
        traceback, = reporter.tracebacks
        assert traceback.exception == 'SlowRequestError: /slow'
        # the snapshot is taken of the thread still serving the request
        assert 'test_slow_request_is_reported_with_the_running_stack' in [
            frame.function_name for frame in traceback.frames]
        assert traceback.context['environ']['PATH_INFO'] == '/slow'
        assert traceback.context['marker'] == 'injected'
        b''.join(app_iter)
    finally:
        app.timer.shutdown(cancel_jobs=True)


def test_excluded_paths_are_not_traced():
    reporter = RecordingReporter()
    app = TraceSlowRequestsMiddleware(ok_app, [reporter], [], interval=0,
                                      exclude_paths=['/static'])
    try:
        environ = wsgi_environ('/static/style.css')
        status, body = run_wsgi(app, environ)
        assert status == '200 OK'
        assert body == b'app-response'
        assert 'BACKLASH_SLOW_TRACING_JOBS' not in environ
    finally:
        app.timer.shutdown(cancel_jobs=True)


def test_completed_response_cancels_the_pending_trace():
    app = TraceSlowRequestsMiddleware(ok_app, [RecordingReporter()], [],
                                      interval=60)
    try:
        environ = wsgi_environ()
        run_wsgi(app, environ)
        assert len(environ['BACKLASH_SLOW_TRACING_JOBS']) == 1
        # the timer thread exits on shutdown only if no job is left pending
        app.timer.shutdown()
        app.timer.join(timeout=2)
        assert not app.timer.is_alive()
    finally:
        app.timer.shutdown(cancel_jobs=True)


def test_timer_runs_scheduled_jobs_and_skips_cancelled_ones():
    timer = Timer()
    timer.daemon = True
    timer.start()
    try:
        done = []
        cancelled = timer.run_later(done.append, 0, 'cancelled')
        timer.cancel(cancelled)
        job = timer.run_later(done.append, 0, 'executed')
        assert wait_for(job.is_finished)
        assert done == ['executed']
        assert not cancelled.is_finished()
    finally:
        timer.shutdown(cancel_jobs=True)


def test_timer_survives_a_job_raising_baseexception():
    def exiting_injector():
        raise SystemExit('context injector bailed out')

    timer = Timer()
    timer.daemon = True
    timer.start()
    try:
        failing = timer.run_later(exiting_injector, 0)
        assert wait_for(failing.is_finished)

        done = []
        job = timer.run_later(done.append, 0, 'executed')
        assert wait_for(job.is_finished)
        assert done == ['executed']
        assert timer.is_alive()
    finally:
        timer.shutdown(cancel_jobs=True)
