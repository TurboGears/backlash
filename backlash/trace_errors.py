import smtplib
import ssl
from email.mime.text import MIMEText

from backlash._compat import string_types, bytes_
from backlash.tbtools import get_current_traceback
from backlash.utils import RequestContext

class TraceErrorsMiddleware(object):
    def __init__(self, application, reporters, context_injectors):
        self.app = application
        self.reporters = reporters
        self.context_injectors = context_injectors

    def __call__(self, environ, start_response):
        app_iter = None
        try:
            app_iter = self.app(environ, start_response)
            for item in app_iter:
                yield item
            if hasattr(app_iter, 'close'):
                app_iter.close()
        except Exception:
            if hasattr(app_iter, 'close'):
                app_iter.close()

            context = RequestContext({'environ':dict(environ)})
            for injector in self.context_injectors:
                context.update(injector(environ))
            traceback = get_current_traceback(skip=1, show_hidden_frames=False, context=context)

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
                yield bytes_('Internal Server Error')

            traceback.log(environ['wsgi.errors'])

            for r in self.reporters:
                try:
                    r.report(traceback)
                except Exception:
                    error = get_current_traceback(skip=1, show_hidden_frames=False)
                    environ['wsgi.errors'].write('\nError while reporting exception with %s\n' % r)
                    environ['wsgi.errors'].write(error.plaintext)

class EmailReporter(object):
    def __init__(self, smtp_server=None, from_address=None, error_email=None,
                 smtp_username=None, smtp_password=None, smtp_use_tls=False,
                 error_subject_prefix='',
                 **unused):
        self.smtp_server = smtp_server
        self.from_address = from_address

        self.smtp_username = smtp_username
        self.smtp_password = smtp_password

        self.smtp_use_tls = smtp_use_tls

        if isinstance(error_email, string_types):
            error_email = [error_email]
        self.error_email = error_email

        self.error_subject_prefix = error_subject_prefix

    def report(self, traceback):
        if not self.smtp_server or not self.from_address:
            return

        msg = self.assemble_email(traceback)

        server = smtplib.SMTP(self.smtp_server)
        if self.smtp_use_tls:
            server.ehlo()
            server.starttls()
            server.ehlo()

        if self.smtp_username and self.smtp_password:
            server.login(self.smtp_username, self.smtp_password)

        result = server.sendmail(self.from_address, self.error_email, msg.as_string())

        try:
            server.quit()
        except ssl.SSLError:
            # SSLError is raised in tls connections on closing sometimes
            pass

    def assemble_email(self, traceback):
        msg = MIMEText(bytes_(traceback.plaintext))
        msg.set_type('text/plain')
        msg.set_param('charset', 'UTF-8')

        subject = bytes_('%s: %s' % (traceback.exc_type, traceback.exc_value))

        msg['Subject'] = bytes_(self.error_subject_prefix + subject)
        msg['From'] = bytes_(self.from_address)
        msg['To'] = bytes_(', '.join(self.error_email))

        return msg
