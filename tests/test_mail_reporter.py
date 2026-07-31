"""Behavioral tests for the email crash reporter.

Covers the assembled message (subject, recipients, body sections), the SMTP
conversation, local frames dumping and the required settings validation.
The network is never touched: smtplib.SMTP is replaced by a recorder.
"""
import email
import smtplib

import pytest

from backlash.tbtools import get_current_traceback
from backlash.tracing.reporters.mail import EmailReporter
from backlash.utils import RequestContext


def install_fake_smtp(monkeypatch):
    """Replace smtplib.SMTP with a recorder: returns the list of connections."""
    connections = []

    class FakeSMTP(object):
        def __init__(self, host, port):
            self.host = host
            self.port = port
            self.sent = []
            self.tls = False
            self.credentials = None
            self.quit_called = False
            connections.append(self)

        def ehlo(self):
            pass

        def starttls(self):
            self.tls = True

        def login(self, username, password):
            self.credentials = (username, password)

        def sendmail(self, from_address, recipients, message):
            self.sent.append((from_address, recipients, message))

        def quit(self):
            self.quit_called = True

    monkeypatch.setattr(smtplib, 'SMTP', FakeSMTP)
    return connections


def crash_traceback(message='boom %d'):
    """Real traceback with a request context, as the middlewares build it."""
    try:
        frame_local = 42  # must be visible when dumping local frames
        raise ZeroDivisionError(message % frame_local)
    except ZeroDivisionError:
        return get_current_traceback(context=RequestContext({'environ': {
            'PATH_INFO': '/crash',
            'REQUEST_METHOD': 'GET',
            'wsgi.url_scheme': 'http',
        }}))


def sent_message(connection):
    """Parse the single message the reporter handed to SMTP."""
    _, _, raw = connection.sent[0]
    return email.message_from_string(raw)


def body_of(message):
    return message.get_payload(0).get_payload(decode=True).decode('utf-8')


def test_report_sends_the_assembled_email(monkeypatch):
    connections = install_fake_smtp(monkeypatch)
    reporter = EmailReporter(smtp_server='smtp.example.com', smtp_port=2525,
                             from_address='crash@example.com',
                             error_email='dev@example.com,ops@example.com',
                             error_subject_prefix='[APP] ')
    reporter.report(crash_traceback())

    connection, = connections
    assert (connection.host, connection.port) == ('smtp.example.com', 2525)
    assert connection.quit_called
    from_address, recipients, _ = connection.sent[0]
    assert from_address == 'crash@example.com'
    assert recipients == ['dev@example.com', 'ops@example.com']

    message = sent_message(connection)
    assert message['Subject'] == '[APP] ZeroDivisionError: boom 42'
    assert message['From'] == 'crash@example.com'
    assert message['To'] == 'dev@example.com, ops@example.com'
    body = body_of(message)
    assert 'TRACEBACK:\nTraceback (most recent call last):' in body
    assert 'ZeroDivisionError: boom 42' in body
    assert "\tPATH_INFO: '/crash'" in body  # CGI keys in the ENVIRON section
    assert "\twsgi.url_scheme: 'http'" in body  # lowercase keys in the WSGI one
    assert body.index('ENVIRON:') < body.index('WSGI:')
    assert 'FRAME #' not in body


def test_multiline_exception_message_is_flattened_in_the_subject(monkeypatch):
    connections = install_fake_smtp(monkeypatch)
    reporter = EmailReporter(smtp_server='smtp.example.com',
                             from_address='crash@example.com',
                             error_email='dev@example.com')
    reporter.report(crash_traceback('boom\non two lines %d'))
    assert sent_message(connections[0])['Subject'] == \
        'ZeroDivisionError: boom on two lines 42'


def test_non_ascii_report_is_utf8_encoded(monkeypatch):
    connections = install_fake_smtp(monkeypatch)
    reporter = EmailReporter(smtp_server='smtp.example.com',
                             from_address='crash@example.com',
                             error_email='dev@example.com')
    reporter.report(crash_traceback('boom pi\u00f9 %d'))
    assert 'boom pi\u00f9 42' in body_of(sent_message(connections[0]))


def test_dump_local_frames_includes_frame_variables(monkeypatch):
    connections = install_fake_smtp(monkeypatch)
    reporter = EmailReporter(smtp_server='smtp.example.com',
                             from_address='crash@example.com',
                             error_email='dev@example.com',
                             dump_local_frames=True,
                             dump_local_frames_count=1)
    reporter.report(crash_traceback())
    body = body_of(sent_message(connections[0]))
    assert 'LAST FRAMES:' in body
    assert 'FRAME #' in body
    assert '         frame_local = 42' in body


def test_tls_and_authentication(monkeypatch):
    connections = install_fake_smtp(monkeypatch)
    reporter = EmailReporter(smtp_server='smtp.example.com',
                             from_address='crash@example.com',
                             error_email=['dev@example.com', 'ops@example.com'],
                             smtp_username='user', smtp_password='secret',
                             smtp_use_tls=True)
    reporter.report(crash_traceback())
    assert connections[0].tls
    assert connections[0].credentials == ('user', 'secret')


def test_incomplete_configuration_is_rejected():
    for missing in ('smtp_server', 'from_address', 'error_email'):
        settings = {'smtp_server': 'smtp.example.com',
                    'from_address': 'crash@example.com',
                    'error_email': 'dev@example.com'}
        del settings[missing]
        with pytest.raises(ValueError) as error:
            EmailReporter(**settings)
        assert 'smtp_server, from_address and error_email' in str(error.value)
