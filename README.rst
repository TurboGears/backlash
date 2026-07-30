About backlash
-------------------------

backlash is a swiss army knife for web applications debugging, which provides:

- An Interactive In Browser Debugger for WSGI and ASGI applications,
  based on a Werkzeug Debugger fork
- Crash reporting by email and on Sentry (WSGI)
- Slow requests reporting by email and on Sentry (WSGI).

Backlash was born as a replacement for WebError in TurboGears2.3 versions.

Installing
-------------------------------

backlash can be installed from pypi::

    pip install backlash

should just work for most of the users. backlash has no runtime dependencies.

Debugging and Console
----------------------------------

Backlash supports both debugging applications on crash and realtime console,
both based on the Werkzeug Debugger.

The debugging function is provided by the ``WsgiDebuggedApplication`` middleware
for WSGI applications and the ``AsgiDebuggedApplication`` middleware for ASGI
applications (Starlette, FastAPI, bare ASGI apps). Wrapping your application
with the middleware will intercept any exception and display the traceback and
an interactive console in your browser.

An interactive console will also be always available at ``/__console__`` path.

``backlash.DebuggedApplication`` (importable also as
``backlash.debug.DebuggedApplication``) is the same class as
``backlash.wsgi.WsgiDebuggedApplication``, so existing WSGI setups keep
working unchanged.

ASGI Applications
+++++++++++++++++++++++++++++

Bare ASGI applications are wrapped directly::

    from backlash.asgi import AsgiDebuggedApplication

    app = AsgiDebuggedApplication(app)

Starlette and FastAPI applications should install the debugger with
``add_middleware`` instead of wrapping the application object::

    app.add_middleware(AsgiDebuggedApplication)

This places the debugger inside Starlette's ``ServerErrorMiddleware``, which
otherwise sends its own 500 response before re-raising, leaving the debugger
no chance to render its page.

Context Injectors
+++++++++++++++++++++++++++++

The debugger middlewares also make possible to provide one or more
``context injectors``, those are simple python functions that will be called when
an exception is raised to retrieve the context to store and make back available during
debugging. Context injectors receive the WSGI environ or the ASGI scope of the
failed request.

Context injectors have to return a dictionary which will be merged into the current
request context, the request context itself will be made available inside the debugger
as the ``ctx`` object.

This feature is used for example by TurboGears to provide back some of the objects
which were available during execution like the current request.

Example
+++++++++++++++++++++++++++++++

The DebuggedApplication middleware is used by TurboGears in the following way::

    def _turbogears_backlash_context(environ):
        tgl = environ.get('tg.locals')
        return {'request':getattr(tgl, 'request', None)}

    app = backlash.DebuggedApplication(app, context_injectors=[_turbogears_backlash_context])


Exception Tracing
---------------------------------------

The ``TraceErrorsMiddleware`` provides a WSGI middleware that intercepts any exception
raised during execution, retrieves a traceback object and provides it to one or more
``reporters`` to log the error.

By default the ``EmailReporter`` and ``SentryReporter`` are provided to send error
reports by email and on Sentry.

The ``EmailReporter`` supports most of the options WebError ErrorMiddleware to provide some
kind of backward compatibility and make possible a quick transition.

While this function is easily replicable using the python logging SMTPHandler, the
TraceErrorsMiddleware is explicitly meant for web applications crash reporting
which has the benefit of being able to provide more complete information and keep a clear
and separate process in managing errors.

Example
++++++++++++++++++++++++++++++++

The TraceErrorsMiddleware is used by TurboGears in the following way::

    from backlash.trace_errors import EmailReporter

    def _turbogears_backlash_context(environ):
       tgl = environ.get('tg.locals')
       return {'request':getattr(tgl, 'request', None)}

    app = backlash.TraceErrorsMiddleware(app, [EmailReporter(**errorware)],
                                         context_injectors=[_turbogears_backlash_context])

Slow Requests Tracing
---------------------------------------

The ``TraceSlowRequestsMiddleware`` provides a WSGI middleware that tracks requests
execution time and reports requests that took more than a specified interval to complete
(by default 25 seconds).

It is also possible to exclude a list of paths that start with a specified string
to avoid reporting long polling connections or other kind of requests that are
expected to have a long life spawn.

Example
++++++++++++++++++++++++++++++++

The TraceSlowRequestsMiddleware is used by TurboGears in the following way::

    from backlash.trace_errors import EmailReporter

    def _turbogears_backlash_context(environ):
       tgl = environ.get('tg.locals')
       return {'request':getattr(tgl, 'request', None)}

    app = backlash.TraceSlowRequestsMiddleware(app, [EmailReporter(**errorware)],
                                               interval=25, exclude_paths=None,
                                               context_injectors=[_turbogears_backlash_context])
