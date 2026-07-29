"""Acceptance tests against a real Starlette application.

Verifies the integration documented in issue #23: installing the debugger
with ``app.add_middleware(AsgiDebuggedApplication)`` places it inside
Starlette's ``ServerErrorMiddleware`` so it catches exceptions before any
response starts, while wrapping the whole app from outside only sees the
exception after Starlette already sent its own 500.
"""
import asyncio

import pytest

starlette = pytest.importorskip('starlette')

from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from backlash.asgi import AsgiDebuggedApplication


async def crash(request):
    frame_local = 42  # inspectable from the debugger console
    raise ZeroDivisionError('boom %d' % frame_local)


async def hello(request):
    return PlainTextResponse('app-response')


def make_app():
    return Starlette(routes=[Route('/', hello), Route('/crash', crash)])


def run_http(app, path='/', qs=b''):
    """Drive the ASGI app in-process: returns (status, headers, body)."""
    scope = {'type': 'http', 'http_version': '1.1', 'method': 'GET',
             'scheme': 'http', 'path': path, 'raw_path': path.encode(),
             'root_path': '', 'query_string': qs, 'headers': [],
             'client': ('testclient', 123), 'server': ('testserver', 80)}
    messages = []

    async def receive():
        return {'type': 'http.request'}

    async def send(message):
        messages.append(message)

    asyncio.run(app(scope, receive, send))
    starts = [m for m in messages if m['type'] == 'http.response.start']
    body = b''.join(m.get('body', b'') for m in messages
                    if m['type'] == 'http.response.body')
    return starts, body


def test_add_middleware_passthrough():
    app = make_app()
    app.add_middleware(AsgiDebuggedApplication)
    starts, body = run_http(app)
    assert starts[0]['status'] == 200
    assert body == b'app-response'


def test_add_middleware_renders_debugger_on_crash():
    # Recommended placement: inside ServerErrorMiddleware, before any
    # response starts, so the full debugger page is served.
    app = make_app()
    app.add_middleware(AsgiDebuggedApplication)
    starts, body = run_http(app, path='/crash')
    assert starts[0]['status'] == 500
    assert b'ZeroDivisionError' in body
    assert b'boom 42' in body
    assert b'SECRET' in body  # interactive debugger page, not a plain 500


def test_add_middleware_frame_eval_through_starlette_stack():
    app = make_app()
    app.add_middleware(AsgiDebuggedApplication)
    run_http(app, path='/crash')
    # Starlette instantiates the middleware inside its stack: find it by
    # walking from ServerErrorMiddleware inward.
    instance = app.middleware_stack.app
    while not isinstance(instance, AsgiDebuggedApplication):
        instance = instance.app
    frame_id = next(fid for fid, frame in instance.frames.items()
                    if 'frame_local' in frame.console.eval('dir()'))
    starts, body = run_http(
        app, path='/crash',
        qs=b'__debugger__=yes&cmd=frame_local&frm=%d&s=%s' % (
            frame_id, instance.secret.encode('ascii')))
    assert starts[0]['status'] == 200
    assert b'42' in body


def test_outer_wrap_reraises_after_starlette_500():
    # Documented caveat: ServerErrorMiddleware sends its plain 500 then
    # re-raises, so an outer wrap sees a started response: it logs,
    # captures, and re-raises to the server without corrupting the wire.
    app = AsgiDebuggedApplication(make_app())
    scope = {'type': 'http', 'http_version': '1.1', 'method': 'GET',
             'scheme': 'http', 'path': '/crash', 'raw_path': b'/crash',
             'root_path': '', 'query_string': b'', 'headers': [],
             'client': ('testclient', 123), 'server': ('testserver', 80)}
    messages = []

    async def receive():
        return {'type': 'http.request'}

    async def send(message):
        messages.append(message)

    with pytest.raises(ZeroDivisionError):
        asyncio.run(app(scope, receive, send))
    starts = [m for m in messages if m['type'] == 'http.response.start']
    body = b''.join(m.get('body', b'') for m in messages
                    if m['type'] == 'http.response.body')
    assert len(starts) == 1 and starts[0]['status'] == 500
    assert b'SECRET' not in body  # Starlette's plain 500, not the debugger
    assert len(app.tracebacks) == 1  # still captured for inspection
