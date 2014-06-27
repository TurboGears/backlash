try:
    from raven.base import Client
    from raven.utils.wsgi import get_current_url, get_headers, get_environ
except ImportError:
    Client = None


class SentryReporter(object):
    def __init__(self, sentry_dsn, **unused):
        if Client is None:
            raise RavenNotAvailable('Raven is not installed, maybe run "pip install raven"')

        self.client = Client(sentry_dsn)

    def report(self, traceback):
        environ = traceback.context.get('environ', {})
        data = {
            'sentry.interfaces.Http': {
                'method': environ.get('REQUEST_METHOD'),
                'url': get_current_url(environ, strip_querystring=True),
                'query_string': environ.get('QUERY_STRING'),
                # TODO
                # 'data': environ.get('wsgi.input'),
                'headers': dict(get_headers(environ)),
                'env': dict(get_environ(environ)),
            }
        }

        is_backlash_event = getattr(traceback.exc_value, 'backlash_event', False)
        if is_backlash_event:
            # Just a Stack Dump request from backlash
            self.client.captureMessage(traceback.exception, data=data,
                                       stack=traceback.frames)
        else:
            # This is a real crash
            self.client.captureException(data=data)


class RavenNotAvailable(Exception):
    pass