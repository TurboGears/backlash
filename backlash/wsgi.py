"""WSGI shell of the interactive traceback debugger."""
from http.client import responses as _HTTP_REASONS
from urllib.parse import parse_qs

from backlash.debugger import DebuggerCore, log
from backlash.utils import RequestContext


class WsgiDebuggedApplication(DebuggerCore):
    """Enables debugging support for a WSGI application::

        from backlash.wsgi import WsgiDebuggedApplication
        from myapp import app
        app = WsgiDebuggedApplication(app, evalex=True)

    See :class:`backlash.debugger.DebuggerCore` for the constructor
    arguments.  Context injectors are called with the WSGI environ.
    """

    def __call__(self, environ, start_response):
        """Dispatch the requests."""
        if self.allow_debug is not None and not self.allow_debug(environ):
            return self.app(environ, start_response)

        query = {key: values[0] for key, values in
                 parse_qs(environ.get('QUERY_STRING', '')).items()}
        response = self.debugger_response(environ.get('PATH_INFO', ''), query)
        if response is not None:
            status, content_type, body = response
            start_response('%d %s' % (status, _HTTP_REASONS[status]),
                           [('Content-Type', content_type),
                            ('Content-Length', str(len(body)))])
            return [body]
        return self.debug_application(environ, start_response)

    def debug_application(self, environ, start_response):
        """Run the application and conserve the traceback frames."""
        app_iter = None
        try:
            try:
                app_iter = self.app(environ, start_response)
                for item in app_iter:
                    yield item
            finally:
                if hasattr(app_iter, 'close'):
                    app_iter.close()
        except Exception:
            context = RequestContext({'environ': dict(environ)})
            for injector in self.context_injectors:
                context.update(injector(environ))

            traceback = self.save_traceback(context)

            try:
                start_response('500 INTERNAL SERVER ERROR', [
                    ('Content-Type', 'text/html; charset=utf-8'),
                    # Disable Chrome's XSS protection, the debug
                    # output can cause false-positives.
                    ('X-XSS-Protection', '0'),
                    ])
            except Exception:
                # if we end up here there has been output but an error
                # occurred.  in that situation we can do nothing fancy any
                # more, better log something into the error log and fall
                # back gracefully.
                environ['wsgi.errors'].write(
                    'Debugging middleware caught exception in streamed '
                    'response at a point where response headers were already '
                    'sent.\n')
            else:
                yield traceback.render_full(
                    evalex=self.evalex,
                    secret=self.secret
                ).encode('utf-8', 'replace')

            # This will lead to double logging in case backlash logger is set to DEBUG
            # but this is actually wanted as some environments, like WebTest, swallow
            # wsgi.environ making the traceback totally disappear.
            log.debug(traceback.plaintext)
            traceback.log(environ['wsgi.errors'])
