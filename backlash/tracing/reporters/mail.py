import smtplib
import ssl
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


class EmailReporter:
    def __init__(self, smtp_server=None, from_address=None, error_email=None,
                 smtp_username=None, smtp_password=None, smtp_use_tls=False,
                 error_subject_prefix='', dump_request=False, dump_request_size=50000,
                 dump_local_frames=False, dump_local_frames_count=2,
                 smtp_port=None, **unused):
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port
        self.from_address = from_address

        self.smtp_username = smtp_username
        self.smtp_password = smtp_password

        self.smtp_use_tls = smtp_use_tls

        if isinstance(error_email, str):
            error_email = error_email.split(",")
        self.error_email = error_email

        self.error_subject_prefix = error_subject_prefix
        self.dump_request = dump_request
        self.dump_request_size = dump_request_size
        self.dump_local_frames = dump_local_frames
        self.dump_local_frames_count = dump_local_frames_count

        if not self.smtp_server or not self.from_address or not self.error_email:
            raise ValueError("Backlash email reporting requires "
                             "smtp_server, from_address and error_email settings") 

    def report(self, traceback):
        msg = self.assemble_email(traceback)

        server = smtplib.SMTP(self.smtp_server, self.smtp_port)
        if self.smtp_use_tls:
            server.ehlo()
            server.starttls()
            server.ehlo()

        if self.smtp_username and self.smtp_password:
            server.login(self.smtp_username, self.smtp_password)

        server.sendmail(self.from_address, self.error_email, msg.as_string())

        try:
            server.quit()
        except ssl.SSLError:
            # SSLError is raised in tls connections on closing sometimes
            pass

    def _repr_value(self, value):
        try:
            value = repr(value)
        except Exception as e:
            # Cope with WebOb response objects that might be unable to get their repr
            value = repr(e)

        return value

    def _format_cgi(self, environ):
        return '\n'.join(
            (f'\t{k}: {self._repr_value(environ[k])}' for k in sorted(environ.keys()) if k.upper() == k))

    def _format_wsgi(self, environ):
        return '\n'.join(
            (f'\t{k}: {self._repr_value(environ[k])}' for k in sorted(environ.keys()) if k.upper() != k))

    def email_body(self, traceback):
        body = f'TRACEBACK:\n{traceback.plaintext}'

        if self.dump_local_frames:
            body += '\n\n\nLAST FRAMES:'
            frames_base_index = len(traceback.frames) - self.dump_local_frames_count
            for idx, frame in enumerate(traceback.frames[-self.dump_local_frames_count:]):
                body += f'\n\tFRAME #{frames_base_index + idx}\n'
                for key, value in frame.locals.items():
                    body += "\t\t%20s = " % key
                    try:
                        body += '%r\n' % (value,)
                    except Exception:
                        body += "<UNABLE TO PRINT VALUE>\n"

        body += f'\n\n\nENVIRON:\n{self._format_cgi(traceback.context["environ"])}'
        body += f'\n\n\nWSGI:\n{self._format_wsgi(traceback.context["environ"])}'

        for entry, value in traceback.context.items():
            if entry == 'environ':
                continue

            body += f'\n\n\n{entry.upper()}:\n\t{value!r}'

        return body

    def assemble_email(self, traceback):
        msg = MIMEMultipart()

        msg['Subject'] = (self.error_subject_prefix + traceback.exception).replace('\n', ' ')
        msg['From'] = self.from_address
        msg['To'] = ', '.join(self.error_email)

        text = MIMEText(self.email_body(traceback).encode('utf-8'), 'plain', 'utf-8')
        text.set_type('text/plain')
        text.set_param('charset', 'UTF-8')
        msg.attach(text)

        request = traceback.context.get('request')
        if self.dump_request and request is not None:
            part = MIMEApplication(request.as_bytes(self.dump_request_size))
            part.add_header('Content-Disposition', 'attachment; filename="request.txt"')
            msg.attach(part)

        return msg
