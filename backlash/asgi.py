# -*- coding: utf-8 -*-
"""ASGI shell of the interactive traceback debugger."""
import sys
from urllib.parse import parse_qs

from backlash.debugger import DebuggerCore, log
from backlash.utils import RequestContext


class AsgiDebuggedApplication(DebuggerCore):
    """Enables debugging support for an ASGI application::

        from backlash.asgi import AsgiDebuggedApplication
        from myapp import app
        app = AsgiDebuggedApplication(app, evalex=True)

    See :class:`backlash.debugger.DebuggerCore` for the constructor
    arguments.  Context injectors are called with the ASGI scope.

    Note for Starlette/FastAPI: install it with
    ``app.add_middleware(AsgiDebuggedApplication)`` so it sits inside
    ``ServerErrorMiddleware``, which otherwise sends its own 500 response
    before re-raising.
    """

    async def __call__(self, scope, receive, send):
        """Dispatch the requests."""
        if scope['type'] != 'http':
            # websocket, lifespan and friends pass through untouched.
            await self.app(scope, receive, send)
            return

        query = {key: values[0] for key, values in
                 parse_qs(scope.get('query_string', b'').decode('latin-1')).items()}
        # TODO(EVO-010): Honor scope root_path when matching debugger paths
        # Why:
        # - The probe matches console_path against scope['path'], which
        #   includes the mount prefix when the app is mounted (e.g. Starlette
        #   Mount or uvicorn --root-path), so /__console__ never matches.
        # Done:
        # - Debugger path matching strips scope['root_path'] before comparing
        #   with console_path, with a test covering a mounted app.
        # Non-Goals:
        # - No rewriting of the relative resource/eval URLs in the rendered
        #   pages: they are query-string based and already mount-safe.
        response = self.debugger_response(scope['path'], query)
        if response is not None:
            await _send_page(send, *response)
            return

        # Track whether the response started so that on crash we know if
        # the debugger page can still be sent.
        response_started = False

        async def tracking_send(message):
            nonlocal response_started
            if message['type'] == 'http.response.start':
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive, tracking_send)
        except Exception:
            context = RequestContext({'scope': dict(scope)})
            for injector in self.context_injectors:
                context.update(injector(scope))

            traceback = self.save_traceback(context)

            if not response_started:
                await _send_page(
                    send, 500, 'text/html; charset=utf-8',
                    traceback.render_full(
                        evalex=self.evalex,
                        secret=self.secret
                    ).encode('utf-8', 'replace'),
                    # Disable Chrome's XSS protection, the debug
                    # output can cause false-positives.
                    extra_headers=[(b'x-xss-protection', b'0')])
            else:
                # Response already on the wire: mirror the WSGI streamed
                # fallback and only log the failure.
                # TODO(EVO-050): Terminate or re-raise on post-start ASGI crash
                # Why:
                # - The probe mirrors the WSGI swallow-and-log fallback, but in
                #   ASGI that leaves the stream open (last body message had
                #   more_body=True, no close, no re-raise): real servers like
                #   uvicorn leave the client hanging.
                # Done:
                # - After logging and capturing, the crash either re-raises to
                #   the server (ASGI ecosystem convention) or a final body
                #   message closes the stream; the strict-xfail acceptance test
                #   tests/test_asgi.py::test_started_crash_terminates_stream
                #   passes and its xfail marker is removed.
                # Non-Goals:
                # - No change to the pre-start crash path or debugger page.
                # - No change to the WSGI streamed fallback.
                log.error(
                    'Debugging middleware caught exception in ASGI '
                    'application at a point where the response was '
                    'already started.')

            log.debug(traceback.plaintext)
            traceback.log(sys.stderr)


async def _send_page(send, status, content_type, body, extra_headers=()):
    headers = [(b'content-type', content_type.encode('latin-1')),
               (b'content-length', str(len(body)).encode('latin-1'))]
    headers.extend(extra_headers)
    await send({'type': 'http.response.start',
                'status': status, 'headers': headers})
    await send({'type': 'http.response.body', 'body': body})
