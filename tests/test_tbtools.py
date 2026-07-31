"""Behavioral tests for traceback capturing and rendering.

Covers the plaintext/HTML renderings of a captured traceback, the paste
``__traceback_hide__`` protocol, syntax errors and the live thread stack
snapshots used to report slow requests.
"""
import io
import threading

from backlash.frtools import get_thread_stack
from backlash.tbtools import get_current_traceback


def crash():
    __traceback_info__ = 'while doing /pay'  # paste's frame annotation protocol
    frame_local = 42  # rendered among the frame locals
    raise ZeroDivisionError('boom %d' % frame_local)


def hidden_caller():
    __traceback_hide__ = True  # noqa: F841  read from frame locals by tbtools
    crash()


def captured_traceback():
    """Capture a real traceback the way the middlewares do."""
    try:
        hidden_caller()
    except ZeroDivisionError:
        return get_current_traceback()


def test_plaintext_traceback():
    traceback = captured_traceback()
    assert traceback.exception_type == 'builtins.ZeroDivisionError'
    assert traceback.exception == 'ZeroDivisionError: boom 42'
    lines = traceback.plaintext.splitlines()
    assert lines[0] == 'Traceback (most recent call last):'
    assert lines[-1] == 'ZeroDivisionError: boom 42'
    assert "raise ZeroDivisionError('boom %d' % frame_local)" in traceback.plaintext
    # frames marked with __traceback_hide__ are dropped from the report
    assert 'hidden_caller' not in [frame.function_name
                                  for frame in traceback.frames]


def test_log_writes_the_plaintext_traceback():
    logfile = io.StringIO()
    captured_traceback().log(logfile)
    assert logfile.getvalue().endswith('ZeroDivisionError: boom 42\n')


def test_render_summary_and_full_page():
    traceback = captured_traceback()
    summary = traceback.render_summary()
    assert '<h3>Traceback <em>(most recent call last)</em>:</h3>' in summary
    assert '<code class="function">crash</code>' in summary
    assert '<blockquote>ZeroDivisionError: boom 42</blockquote>' in summary
    # __traceback_info__ annotates the frame entry as a tooltip
    assert 'title="while doing /pay"' in summary
    page = traceback.render_full(evalex=True, secret='s3cret')
    assert '<h1>builtins.ZeroDivisionError</h1>' in page
    assert 'EVALEX = true' in page
    assert 'SECRET = "s3cret"' in page
    assert 'TRACEBACK = %d' % traceback.id in page


def test_frame_locals_and_source_are_exposed():
    frame = captured_traceback().frames[-1]
    assert frame.function_name == 'crash'
    assert frame.locals['frame_local'] == 42
    assert frame.current_line.strip() == \
        "raise ZeroDivisionError('boom %d' % frame_local)"
    source = frame.render_source()
    assert '<table class=source>' in source
    assert 'class="line in-frame current"' in source  # the crashing line


def test_syntax_errors_are_rendered_as_such():
    try:
        compile('1 +', '<broken>', 'exec')
    except SyntaxError:
        traceback = get_current_traceback()
    assert traceback.is_syntax_error
    assert 'SyntaxError' in traceback.exception
    summary = traceback.render_summary()
    assert '<h3>Syntax Error</h3>' in summary
    assert '<pre class=syntaxerror>' in summary


def test_thread_stack_snapshot():
    traceback = get_thread_stack(threading.get_ident(), '/slow',
                                 error_type='SlowRequestError')
    # the fake exception type is reported without the backlash module prefix
    assert traceback.exception_type == '__main__.SlowRequestError'
    assert traceback.exception == 'SlowRequestError: /slow'
    assert traceback.frames[-1].function_name == 'get_thread_stack'
    assert 'test_thread_stack_snapshot' in [frame.function_name
                                            for frame in traceback.frames]
