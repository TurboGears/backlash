"""Behavioral tests for the WSGI error tracing middleware.

Covers the 500 response produced on crash, the traceback handed to the
reporters, reporter failures being swallowed and the ``backlash.exc_info``
handoff used by applications that catch the exception themselves.
"""
import io
import sys

from backlash import TraceErrorsMiddleware


class RecordingReporter(object):
    def __init__(self):
        self.tracebacks = []

    def report(self, traceback):
        self.tracebacks.append(traceback)


class BrokenReporter(object):
    def report(self, traceback):
        raise RuntimeError('reporter is down')


def ok_app(environ, start_response):
    start_response('200 OK', [('Content-Type', 'text/plain')])
    return [b'app-response']


def failing_app(environ, start_response):
    frame_local = 42  # must show up in the reported traceback
    raise ZeroDivisionError('boom %d' % frame_local)


def streaming_failing_app(environ, start_response):
    start_response('200 OK', [('Content-Type', 'text/plain')])
    yield b'partial'
    raise ZeroDivisionError('boom after start')


def recovering_app(environ, start_response):
    """App that swallows the error and hands it over through the environ."""
    try:
        raise ValueError('handled downstream')
    except ValueError:
        environ['backlash.exc_info'] = sys.exc_info()
        environ['backlash.exc_environ'] = dict(environ, PATH_INFO='/deferred')
    start_response('200 OK', [('Content-Type', 'text/plain')])
    return [b'recovered']


def run_wsgi(app, path='/'):
    """Minimal in-process WSGI client: returns (status, headers, body, environ)."""
    environ = {
        'REQUEST_METHOD': 'GET',
        'PATH_INFO': path,
        'QUERY_STRING': '',
        'SERVER_NAME': 'localhost',
        'SERVER_PORT': '80',
        'wsgi.url_scheme': 'http',
        'wsgi.errors': io.StringIO(),
    }
    captured = {}

    def start_response(status, headers, exc_info=None):
        # Real servers refuse a second start_response once output began.
        if 'status' in captured and exc_info is None:
            raise AssertionError('response already started')
        captured['status'] = status
        captured['headers'] = dict(headers)

    body = b''.join(app(environ, start_response))
    return captured.get('status'), captured.get('headers', {}), body, environ


def test_passthrough():
    reporter = RecordingReporter()
    app = TraceErrorsMiddleware(ok_app, [reporter], [])
    status, _, body, _ = run_wsgi(app)
    assert status == '200 OK'
    assert body == b'app-response'
    assert reporter.tracebacks == []


def test_crash_reports_traceback_and_serves_error_page():
    reporter = RecordingReporter()
    app = TraceErrorsMiddleware(failing_app, [reporter], [])
    status, headers, body, environ = run_wsgi(app)
    assert status == '500 INTERNAL SERVER ERROR'
    assert headers['Content-Type'] == 'text/html; charset=utf-8'
    assert headers['X-XSS-Protection'] == '0'
    assert body == b'Internal Server Error'
    traceback, = reporter.tracebacks
    assert traceback.plaintext.endswith('ZeroDivisionError: boom 42')
    assert "raise ZeroDivisionError('boom %d' % frame_local)" in traceback.plaintext
    assert traceback.context['environ']['PATH_INFO'] == '/'
    assert 'ZeroDivisionError: boom 42' in environ['wsgi.errors'].getvalue()


def test_crash_is_logged_at_debug_level(caplog):
    app = TraceErrorsMiddleware(failing_app, [], [])
    with caplog.at_level('DEBUG', logger='backlash'):
        run_wsgi(app)
    assert 'ZeroDivisionError: boom 42' in caplog.text


def test_context_injectors_extend_the_reported_context():
    reporter = RecordingReporter()
    seen = []

    def injector(environ):
        seen.append(environ['PATH_INFO'])
        return {'marker': 'injected'}

    app = TraceErrorsMiddleware(failing_app, [reporter], [injector])
    run_wsgi(app, path='/crash')
    assert seen == ['/crash']
    traceback, = reporter.tracebacks
    assert traceback.context['marker'] == 'injected'


def test_crash_after_response_started_only_logs():
    reporter = RecordingReporter()
    app = TraceErrorsMiddleware(streaming_failing_app, [reporter], [])
    status, _, body, environ = run_wsgi(app)
    assert status == '200 OK'
    assert body == b'partial'  # no error page once output has been sent
    errors = environ['wsgi.errors'].getvalue()
    assert 'response headers were already sent' in errors
    assert 'ZeroDivisionError: boom after start' in errors
    assert len(reporter.tracebacks) == 1  # the error is still reported


def test_failing_reporter_does_not_break_the_response():
    reporter = RecordingReporter()
    app = TraceErrorsMiddleware(failing_app, [BrokenReporter(), reporter], [])
    status, _, body, environ = run_wsgi(app)
    assert status == '500 INTERNAL SERVER ERROR'
    assert body == b'Internal Server Error'
    assert len(reporter.tracebacks) == 1  # later reporters still run
    errors = environ['wsgi.errors'].getvalue()
    assert 'Error while reporting exception with' in errors
    assert 'RuntimeError: reporter is down' in errors


def test_exception_recorded_in_environ_is_reported():
    reporter = RecordingReporter()
    app = TraceErrorsMiddleware(recovering_app, [reporter], [])
    status, _, body, _ = run_wsgi(app)
    assert status == '200 OK'
    assert body == b'recovered'  # the app response is left untouched
    traceback, = reporter.tracebacks
    assert traceback.plaintext.endswith('ValueError: handled downstream')
    # backlash.exc_environ replaces the environ the report is built from
    assert traceback.context['environ']['PATH_INFO'] == '/deferred'
