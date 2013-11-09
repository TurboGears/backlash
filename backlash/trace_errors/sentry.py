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

        self.client.captureException(
            data={
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
        )


class RavenNotAvailable(Exception):
    pass