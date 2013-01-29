About backlash
-------------------------

backlash is a standalone version of the Werkzeug Debugger based on WebOb
adapted to support for Python3.

backlash has born as a future replacement for WebError in upcoming TurboGears2 versions.

Installing
-------------------------------

backlash can be installed from pypi::

    easy_install backlash

or::

    pip install backlash

should just work for most of the users

Debugging and Console
----------------------------------

Backlash supports both debugging applications on crash and realtime console,
both are based on the Werkzeug Debugger and adapted to work with WebOb.

The debugging function is provided by the ``DebuggedApplication`` middleware,
wrapping your application with this middleware will intercept any exception
and display the traceback and an interactive console in your browser.

An interactive console will also be always available at ``/__console__`` path.

Context Injectors
+++++++++++++++++++++++++++++

The ``DebuggedApplication`` middleware also makes possible to provide one or more
``context injectors``, those are simple python functions that will be called when
an exception is raised to retrieve the context to store and make back available during
debugging.

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

By default the ``EmailReporter`` class is provided to send error reports by email.
This object supports most of the options WebError ErrorMiddleware to provide some
kind of backward compatibility and make possible a quick transition.

While this function is easily replicable using the python logging SMTPHandler, the
TraceErrorsMiddleware is explicitly meant for web applications crash reporting
which has the benefit of being able to provide more complete informations and keep a clear
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