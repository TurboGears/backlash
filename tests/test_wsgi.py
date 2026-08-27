"""Behavioral tests for the WSGI debugger middleware."""
import io

import pytest

from backlash.wsgi import WsgiDebuggedApplication


def ok_app(environ, start_response):
    start_response('200 OK', [('Content-Type', 'text/plain')])
    return [b'app-response']


def failing_app(environ, start_response):
    frame_local = 42  # inspectable from the debugger console
    raise ZeroDivisionError('boom %d' % frame_local)


def streaming_failing_app(environ, start_response):
    start_response('200 OK', [('Content-Type', 'text/plain')])
    yield b'partial'
    raise ZeroDivisionError('boom after start')


def run_wsgi(app, path='/', qs=''):
    """Minimal in-process WSGI client: returns (status, headers, body, environ)."""
    environ = {
        'REQUEST_METHOD': 'GET',
        'PATH_INFO': path,
        'QUERY_STRING': qs,
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
    app = WsgiDebuggedApplication(ok_app)
    status, _, body, _ = run_wsgi(app)
    assert status == '200 OK'
    assert body == b'app-response'


def test_exception_renders_debugger_page():
    app = WsgiDebuggedApplication(failing_app)
    status, headers, body, _ = run_wsgi(app)
    assert status == '500 INTERNAL SERVER ERROR'
    assert headers['Content-Type'] == 'text/html; charset=utf-8'
    assert headers['X-XSS-Protection'] == '0'
    assert b'ZeroDivisionError' in body
    assert b'boom 42' in body
    assert app.secret.encode('ascii') in body  # evalex wiring in the page


def test_exception_is_logged_to_wsgi_errors():
    app = WsgiDebuggedApplication(failing_app)
    *_, environ = run_wsgi(app)
    assert 'ZeroDivisionError' in environ['wsgi.errors'].getvalue()


def test_streamed_response_falls_back_to_log_only():
    app = WsgiDebuggedApplication(streaming_failing_app)
    status, _, body, environ = run_wsgi(app)
    assert status == '200 OK'
    assert body == b'partial'  # no debugger HTML after output started
    errors = environ['wsgi.errors'].getvalue()
    assert 'already' in errors
    assert 'ZeroDivisionError' in errors


def test_frame_command_evaluates_in_crash_context():
    app = WsgiDebuggedApplication(failing_app)
    run_wsgi(app)  # trigger the crash to record frames
    frame_id = next(fid for fid, frame in app.frames.items()
                    if 'frame_local' in frame.console.eval('dir()'))
    status, _, body, _ = run_wsgi(
        app, qs='__debugger__=yes&cmd=frame_local&frm=%d&s=%s' % (
            frame_id, app.secret))
    assert status == '200 OK'
    assert b'42' in body


def test_command_rejected_without_secret():
    app = WsgiDebuggedApplication(failing_app)
    run_wsgi(app)
    frame_id = next(iter(app.frames))
    # wrong secret: the request falls through to the wrapped app
    status, _, body, _ = run_wsgi(
        app, qs='__debugger__=yes&cmd=frame_local&frm=%d&s=wrong' % frame_id)
    assert status == '500 INTERNAL SERVER ERROR'  # wrapped app crashed again
    assert body.startswith(b'<!DOCTYPE HTML')  # full crash page, not an eval result


def test_source_view():
    app = WsgiDebuggedApplication(failing_app)
    run_wsgi(app)
    frame_id = next(iter(app.frames))
    status, _, body, _ = run_wsgi(
        app, qs='__debugger__=yes&cmd=source&frm=%d&s=%s' % (
            frame_id, app.secret))
    assert status == '200 OK'
    # the source viewer, not the full crash page
    assert not body.startswith(b'<!DOCTYPE HTML')
    assert b'raise ZeroDivisionError' in body


def test_source_rejected_without_secret():
    app = WsgiDebuggedApplication(failing_app)
    run_wsgi(app)
    frame_id = next(iter(app.frames))
    status, _, body, _ = run_wsgi(
        app, qs='__debugger__=yes&cmd=source&frm=%d&s=wrong' % frame_id)
    assert status == '500 INTERNAL SERVER ERROR'  # fell through, app crashed
    assert body.startswith(b'<!DOCTYPE HTML')


def test_eval_command_disabled_without_evalex():
    app = WsgiDebuggedApplication(failing_app, evalex=False)
    run_wsgi(app)
    frame_id = next(iter(app.frames))
    # correct secret, but evalex is off: no code execution, fall through
    status, _, body, _ = run_wsgi(
        app, qs='__debugger__=yes&cmd=frame_local&frm=%d&s=%s' % (
            frame_id, app.secret))
    assert status == '500 INTERNAL SERVER ERROR'
    assert body.startswith(b'<!DOCTYPE HTML')


def test_garbage_frame_id_falls_through_to_app():
    app = WsgiDebuggedApplication(ok_app)
    status, _, body, _ = run_wsgi(
        app, qs='__debugger__=yes&cmd=1%%2B1&frm=garbage&s=%s' % app.secret)
    assert body == b'app-response'  # no crash inside the middleware


def test_frames_from_multiple_crashes_remain_inspectable():
    app = WsgiDebuggedApplication(failing_app)
    run_wsgi(app)
    frame_id = next(fid for fid, frame in app.frames.items()
                    if 'frame_local' in frame.console.eval('dir()'))
    run_wsgi(app)
    assert len(app.tracebacks) == 2
    # frames of the first crash still evaluate after the second one
    status, _, body, _ = run_wsgi(
        app, qs='__debugger__=yes&cmd=frame_local&frm=%d&s=%s' % (
            frame_id, app.secret))
    assert b'42' in body


def test_static_resource():
    app = WsgiDebuggedApplication(ok_app)
    status, headers, body, _ = run_wsgi(
        app, qs='__debugger__=yes&cmd=resource&f=style.css')
    assert status == '200 OK'
    assert headers['Content-Type'] == 'text/css'
    assert headers['Content-Length'] == str(len(body))
    assert body


def test_resource_path_traversal_blocked():
    app = WsgiDebuggedApplication(ok_app)
    status, _, body, _ = run_wsgi(
        app, qs='__debugger__=yes&cmd=resource&f=../debugger.py')
    assert status == '404 Not Found'
    assert body == b'Not Found'


def test_missing_resource_is_404():
    app = WsgiDebuggedApplication(ok_app)
    status, *_ = run_wsgi(app, qs='__debugger__=yes&cmd=resource&f=nope.css')
    assert status == '404 Not Found'


def test_console_page_and_eval():
    app = WsgiDebuggedApplication(ok_app)
    status, _, body, _ = run_wsgi(app, path='/__console__')
    assert status == '200 OK'
    assert b'CONSOLE_MODE = true' in body
    # the console page allocates frame 0 for evaluation
    status, _, body, _ = run_wsgi(
        app, qs='__debugger__=yes&cmd=6*7&frm=0&s=%s' % app.secret)
    assert b'42' in body


def test_console_disabled_without_evalex():
    app = WsgiDebuggedApplication(ok_app, evalex=False)
    status, _, body, _ = run_wsgi(app, path='/__console__')
    assert body == b'app-response'


def test_context_injectors_receive_environ():
    seen = []

    def injector(environ):
        seen.append(environ)
        return {'marker': 'injected'}

    app = WsgiDebuggedApplication(failing_app, context_injectors=[injector])
    run_wsgi(app)
    assert seen and seen[0]['PATH_INFO'] == '/'
    traceback = next(iter(app.tracebacks.values()))
    assert traceback.context['marker'] == 'injected'


def test_allow_debug_false_lets_exception_propagate_uncaught():
    app = WsgiDebuggedApplication(failing_app, allow_debug=lambda environ: False)
    with pytest.raises(ZeroDivisionError):
        run_wsgi(app)
    assert not app.tracebacks  # denied requests are never captured


def test_allow_debug_false_console_endpoint_reaches_wrapped_app_untouched():
    app = WsgiDebuggedApplication(ok_app, allow_debug=lambda environ: False)
    status, _, body, _ = run_wsgi(
        app, qs='__debugger__=yes&cmd=resource&f=style.css')
    assert status == '200 OK'
    assert body == b'app-response'  # not the static resource


def test_allow_debug_receives_environ_and_true_preserves_behavior():
    seen = []

    def allow_debug(environ):
        seen.append(environ)
        return True

    app = WsgiDebuggedApplication(failing_app, allow_debug=allow_debug)
    status, _, body, _ = run_wsgi(app)
    assert seen and seen[0]['PATH_INFO'] == '/'
    assert status == '500 INTERNAL SERVER ERROR'
    assert app.secret.encode('ascii') in body


def test_allow_debug_reevaluated_on_every_request():
    allowed = {'value': True}
    app = WsgiDebuggedApplication(
        failing_app, allow_debug=lambda environ: allowed['value'])

    run_wsgi(app)  # allowed: crash captured, secret handed out
    frame_id = next(fid for fid, frame in app.frames.items()
                    if 'frame_local' in frame.console.eval('dir()'))

    allowed['value'] = False
    with pytest.raises(ZeroDivisionError):
        # a stale secret from an earlier allowed request no longer works
        run_wsgi(
            app, qs='__debugger__=yes&cmd=frame_local&frm=%d&s=%s' % (
                frame_id, app.secret))


def test_backward_compatible_import_path():
    # TurboGears imports the WSGI middleware from backlash.debug
    from backlash.debug import DebuggedApplication
    assert DebuggedApplication is WsgiDebuggedApplication
