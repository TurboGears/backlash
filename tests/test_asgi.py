"""Behavioral tests for the ASGI debugger middleware."""
import asyncio

import pytest

from backlash.asgi import AsgiDebuggedApplication


async def ok_app(scope, receive, send):
    await send({'type': 'http.response.start', 'status': 200,
                'headers': [(b'content-type', b'text/plain')]})
    await send({'type': 'http.response.body', 'body': b'app-response'})


async def failing_app(scope, receive, send):
    frame_local = 42  # inspectable from the debugger console
    raise ZeroDivisionError('boom %d' % frame_local)


async def streaming_failing_app(scope, receive, send):
    await send({'type': 'http.response.start', 'status': 200,
                'headers': [(b'content-type', b'text/plain')]})
    await send({'type': 'http.response.body', 'body': b'partial',
                'more_body': True})
    raise ZeroDivisionError('boom after start')


def run_asgi(app, path='/', qs=b'', scope_type='http', root_path=''):
    """Minimal in-process ASGI client: returns the sent messages."""
    scope = {'type': scope_type, 'method': 'GET', 'path': path,
             'query_string': qs, 'headers': [], 'root_path': root_path}
    messages = []

    async def receive():
        return {'type': 'http.request'}

    async def send(message):
        messages.append(message)

    asyncio.run(app(scope, receive, send))
    return messages


def response_of(messages):
    """Collapse ASGI messages into (status, headers, body)."""
    start = next(m for m in messages if m['type'] == 'http.response.start')
    body = b''.join(m.get('body', b'') for m in messages
                    if m['type'] == 'http.response.body')
    return start['status'], dict(start['headers']), body


def test_passthrough():
    app = AsgiDebuggedApplication(ok_app)
    status, _, body = response_of(run_asgi(app))
    assert status == 200
    assert body == b'app-response'


def test_non_http_scopes_untouched():
    seen = []

    async def recording_app(scope, receive, send):
        seen.append(scope['type'])

    app = AsgiDebuggedApplication(recording_app)
    # lifespan scopes have no path/query_string: they must not be inspected
    asyncio.run(app({'type': 'lifespan'}, None, None))
    asyncio.run(app({'type': 'websocket'}, None, None))
    assert seen == ['lifespan', 'websocket']


def test_exception_renders_debugger_page():
    app = AsgiDebuggedApplication(failing_app)
    status, headers, body = response_of(run_asgi(app))
    assert status == 500
    assert headers[b'content-type'] == b'text/html; charset=utf-8'
    assert headers[b'x-xss-protection'] == b'0'
    assert b'ZeroDivisionError' in body
    assert b'boom 42' in body
    assert app.secret.encode('ascii') in body  # evalex wiring in the page


def test_started_response_falls_back_to_log_only(caplog):
    app = AsgiDebuggedApplication(streaming_failing_app)
    with caplog.at_level('ERROR', logger='backlash'):
        messages = run_asgi(app)
    # exception swallowed, no second response.start on the wire
    starts = [m for m in messages if m['type'] == 'http.response.start']
    assert len(starts) == 1 and starts[0]['status'] == 200
    assert len(app.tracebacks) == 1  # still captured for inspection
    assert 'already started' in caplog.text  # failure is actually logged


@pytest.mark.xfail(strict=True,
                   reason='EVO-050: post-start crash leaves the stream open')
def test_started_crash_terminates_stream():
    # Acceptance for EVO-050: after a crash mid-response the middleware must
    # not leave the client hanging: either the exception propagates to the
    # server or a final body message closes the stream.
    app = AsgiDebuggedApplication(streaming_failing_app)
    try:
        messages = run_asgi(app)
    except ZeroDivisionError:
        return  # re-raised to the server: acceptable
    bodies = [m for m in messages if m['type'] == 'http.response.body']
    assert bodies and bodies[-1].get('more_body', False) is False


def test_frame_command_evaluates_in_crash_context():
    app = AsgiDebuggedApplication(failing_app)
    run_asgi(app)  # trigger the crash to record frames
    frame_id = next(fid for fid, frame in app.frames.items()
                    if 'frame_local' in frame.console.eval('dir()'))
    status, _, body = response_of(run_asgi(
        app, qs=b'__debugger__=yes&cmd=frame_local&frm=%d&s=%s' % (
            frame_id, app.secret.encode('ascii'))))
    assert status == 200
    assert b'42' in body


def test_command_rejected_without_secret():
    app = AsgiDebuggedApplication(failing_app)
    run_asgi(app)
    frame_id = next(iter(app.frames))
    # wrong secret: the request falls through to the wrapped app
    status, _, body = response_of(run_asgi(
        app, qs=b'__debugger__=yes&cmd=frame_local&frm=%d&s=wrong' % frame_id))
    assert status == 500  # wrapped app crashed again
    assert body.startswith(b'<!DOCTYPE HTML')  # full crash page, not an eval result


def test_source_view():
    app = AsgiDebuggedApplication(failing_app)
    run_asgi(app)
    frame_id = next(iter(app.frames))
    status, _, body = response_of(run_asgi(
        app, qs=b'__debugger__=yes&cmd=source&frm=%d&s=%s' % (
            frame_id, app.secret.encode('ascii'))))
    assert status == 200
    # the source viewer, not the full crash page
    assert not body.startswith(b'<!DOCTYPE HTML')
    assert b'raise ZeroDivisionError' in body


def test_source_rejected_without_secret():
    app = AsgiDebuggedApplication(failing_app)
    run_asgi(app)
    frame_id = next(iter(app.frames))
    status, _, body = response_of(run_asgi(
        app, qs=b'__debugger__=yes&cmd=source&frm=%d&s=wrong' % frame_id))
    assert status == 500  # fell through, app crashed again
    assert body.startswith(b'<!DOCTYPE HTML')


def test_eval_command_disabled_without_evalex():
    app = AsgiDebuggedApplication(failing_app, evalex=False)
    run_asgi(app)
    frame_id = next(iter(app.frames))
    # correct secret, but evalex is off: no code execution, fall through
    status, _, body = response_of(run_asgi(
        app, qs=b'__debugger__=yes&cmd=frame_local&frm=%d&s=%s' % (
            frame_id, app.secret.encode('ascii'))))
    assert status == 500
    assert body.startswith(b'<!DOCTYPE HTML')


def test_console_disabled_without_evalex():
    app = AsgiDebuggedApplication(ok_app, evalex=False)
    _, _, body = response_of(run_asgi(app, path='/__console__'))
    assert body == b'app-response'


def test_garbage_frame_id_falls_through_to_app():
    app = AsgiDebuggedApplication(ok_app)
    _, _, body = response_of(run_asgi(
        app, qs=b'__debugger__=yes&cmd=1%%2B1&frm=garbage&s=%s' %
        app.secret.encode('ascii')))
    assert body == b'app-response'  # no crash inside the middleware


def test_static_resource():
    app = AsgiDebuggedApplication(ok_app)
    status, headers, body = response_of(run_asgi(
        app, qs=b'__debugger__=yes&cmd=resource&f=style.css'))
    assert status == 200
    assert headers[b'content-type'] == b'text/css'
    assert headers[b'content-length'] == str(len(body)).encode('ascii')
    assert body


def test_resource_path_traversal_blocked():
    app = AsgiDebuggedApplication(ok_app)
    status, _, body = response_of(run_asgi(
        app, qs=b'__debugger__=yes&cmd=resource&f=../debugger.py'))
    assert status == 404
    assert body == b'Not Found'


def test_missing_resource_is_404():
    app = AsgiDebuggedApplication(ok_app)
    status, *_ = response_of(run_asgi(
        app, qs=b'__debugger__=yes&cmd=resource&f=nope.css'))
    assert status == 404


def test_console_page_and_eval():
    app = AsgiDebuggedApplication(ok_app)
    status, _, body = response_of(run_asgi(app, path='/__console__'))
    assert status == 200
    assert b'CONSOLE_MODE = true' in body
    # the console page allocates frame 0 for evaluation
    status, _, body = response_of(run_asgi(
        app, qs=b'__debugger__=yes&cmd=6*7&frm=0&s=%s' %
        app.secret.encode('ascii')))
    assert b'42' in body


def test_console_reachable_under_mounted_root_path():
    # Acceptance for EVO-010: when the app is mounted (e.g. Starlette Mount
    # or uvicorn --root-path), scope['path'] carries the mount prefix and
    # the console must still be reachable at <mount>/__console__.
    app = AsgiDebuggedApplication(ok_app)
    status, _, body = response_of(run_asgi(
        app, path='/mounted/__console__', root_path='/mounted'))
    assert status == 200
    assert b'CONSOLE_MODE = true' in body


def test_context_injectors_receive_scope():
    seen = []

    def injector(scope):
        seen.append(scope)
        return {'marker': 'injected'}

    app = AsgiDebuggedApplication(failing_app, context_injectors=[injector])
    run_asgi(app)
    assert seen and seen[0]['type'] == 'http'
    traceback = next(iter(app.tracebacks.values()))
    assert traceback.context['marker'] == 'injected'
