"""Transport-agnostic core of the interactive traceback debugger.

``DebuggerCore`` owns the debugger state (captured tracebacks, per-frame
consoles, session secret) and serves the debugger endpoints (static
resources, source viewer, standalone console, expression evaluation) as
plain ``(status, content_type, body)`` responses.

The WSGI and ASGI shells in :mod:`backlash.wsgi` and :mod:`backlash.asgi`
adapt request parsing, response sending, and exception capture to their
transport.
"""
import logging
import mimetypes
from os.path import basename, dirname, isfile, join

from backlash.console import Console
from backlash.tbtools import get_current_traceback, render_console_html
from backlash.utils import gen_salt

log = logging.getLogger('backlash')


class DebuggerCore:
    """State and endpoints shared by the WSGI and ASGI debugger middlewares.

    :param app: the wrapped application (WSGI or ASGI, owned by the shell).
    :param evalex: enable exception evaluation feature (interactive
                   debugging).  This requires a non-forking server.
    :param console_path: the URL for a general purpose console.
    :param console_init_func: the function that is executed before starting
                              the general purpose console.  The return value
                              is used as initial namespace.
    :param show_hidden_frames: by default hidden traceback frames are skipped.
                               You can show them by setting this parameter
                               to `True`.
    :param context_injectors: functions called with the request environment
                              (WSGI environ or ASGI scope) on crash; their
                              return values become debugging context.
    :param allow_debug: optional callable invoked with the request
                        environment (WSGI environ or ASGI scope) on every
                        request, before any debugger behavior. When it
                        returns a false value, the request bypasses the
                        debugger entirely, as if it were disabled just for
                        that request. ``None`` (the default) always allows
                        it, unchanged from prior releases.
    """
    def __init__(self, app, evalex=True, console_path='/__console__',
                 console_init_func=None, show_hidden_frames=False,
                 lodgeit_url=None, context_injectors=None, allow_debug=None):
        if not console_init_func:
            console_init_func = dict
        self.app = app
        self.evalex = evalex
        self.frames = {}
        self.tracebacks = {}
        self.console_path = console_path
        self.console_init_func = console_init_func
        self.show_hidden_frames = show_hidden_frames
        self.secret = gen_salt(20)
        self.context_injectors = context_injectors or []
        self.allow_debug = allow_debug

        if lodgeit_url is not None:
            from warnings import warn
            warn(DeprecationWarning('The lodgeit_url parameter is unused, '
                                    'pasting tracebacks is no longer supported.'))

    def debugger_response(self, path, query):
        """Serve the debugger endpoints for a request.

        ``query`` maps each query-string key to its first value.  Returns a
        ``(status, content_type, body)`` tuple when the request targets a
        debugger endpoint, or ``None`` when it belongs to the wrapped app.
        """
        # important: don't ever access the incoming form data here!
        # Otherwise the application won't have access to it any more.
        if query.get('__debugger__') == 'yes':
            cmd = query.get('cmd')
            arg = query.get('f')
            secret = query.get('s')
            frame = self.frames.get(_as_int(query.get('frm')))

            if cmd == 'resource' and arg:
                return self.get_resource(arg)
            elif cmd == 'source' and frame and self.secret == secret:
                return self.get_source(frame)
            elif self.evalex and cmd is not None and frame is not None and \
                 self.secret == secret:
                return self.execute_command(cmd, frame)
        elif self.evalex and self.console_path is not None and \
             path == self.console_path:
            return self.display_console()
        return None

    def save_traceback(self, context):
        """Capture the exception currently being handled and store its
        frames so the debugger endpoints can inspect them later."""
        traceback = get_current_traceback(
            skip=1, show_hidden_frames=self.show_hidden_frames,
            context=context)
        for frame in traceback.frames:
            self.frames[frame.id] = frame
        self.tracebacks[traceback.id] = traceback
        return traceback

    def execute_command(self, command, frame):
        """Execute a command in a console."""
        return 200, 'text/html; charset=utf-8', \
            frame.console.eval(command).encode('utf-8', 'replace')

    def display_console(self):
        """Display a standalone shell."""
        if 0 not in self.frames:
            self.frames[0] = _ConsoleFrame(self.console_init_func())
        return 200, 'text/html; charset=utf-8', \
            render_console_html(secret=self.secret).encode('utf-8')

    def get_source(self, frame):
        """Render the source viewer."""
        return 200, 'text/html; charset=utf-8', \
            frame.render_source().encode('utf-8', 'replace')

    def get_resource(self, filename):
        """Return a static resource from the statics folder."""
        filename = join(dirname(__file__), 'statics', basename(filename))
        if isfile(filename):
            mimetype = mimetypes.guess_type(filename)[0] \
                or 'application/octet-stream'
            with open(filename, 'rb') as f:
                return 200, mimetype, f.read()
        return 404, 'text/plain', b'Not Found'


class _ConsoleFrame:
    """Helper class so that we can reuse the frame console code for the
    standalone console.
    """

    def __init__(self, namespace):
        self.console = Console(namespace)
        self.id = 0


def _as_int(value):
    # Query values come straight from the client: garbage must not crash
    # the debugger, it just matches no stored frame/traceback.
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
