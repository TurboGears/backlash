"""Behavioral tests for the interactive debugger console.

Covers evaluating code in the frame namespace, the HTML rendering of results
and printed output, the ``dump``/``help`` helpers and error reporting.
Every test restores sys.stdout, which the console hijacks process wide.
"""
import sys

from backlash.console import Console


def evaluate(monkeypatch, source, globals=None, locals=None, context=None):
    """Run one console statement and give back its HTML transcript."""
    # the console replaces sys.stdout globally and never restores it
    monkeypatch.setattr(sys, 'stdout', sys.stdout)
    return Console(globals, locals, context).eval(source)


def test_expression_result_is_rendered_as_html(monkeypatch):
    assert evaluate(monkeypatch, '6*7') == \
        '>>> 6*7\n<span class="number">42</span>'


def test_code_runs_in_the_given_namespaces(monkeypatch):
    transcript = evaluate(monkeypatch, 'frame_local + offset',
                          globals={'offset': 1}, locals={'frame_local': 42})
    assert transcript.endswith('<span class="number">43</span>')


def test_context_is_available_as_ctx(monkeypatch):
    transcript = evaluate(monkeypatch, 'ctx["request"]',
                          context={'request': 'fake-request'})
    assert transcript.endswith('<span class="string">\'fake-request\'</span>')


def test_printed_output_is_escaped(monkeypatch):
    assert evaluate(monkeypatch, "print('<b>')") == ">>> print('<b>')\n&lt;b&gt;\n"


def test_dump_lists_the_object_contents(monkeypatch):
    transcript = evaluate(monkeypatch, 'dump({"a": 1})')
    assert '<h3>Contents of dict object at' in transcript
    assert '<tr><th>a<td><pre class=repr><span class="number">1</span></pre>' \
        in transcript


def test_dump_of_non_string_keyed_dict_falls_back_to_details(monkeypatch):
    # only string keys can be listed as contents, anything else is introspected
    assert '<h3>Details for dict object at' in evaluate(monkeypatch, 'dump({1: "x"})')


def test_dump_without_arguments_lists_the_frame_locals(monkeypatch):
    transcript = evaluate(monkeypatch, 'dump()', locals={'frame_local': 42})
    assert '<h3>Local variables in frame</h3>' in transcript
    assert '<tr><th>frame_local<td><pre class=repr>' \
        '<span class="number">42</span></pre>' in transcript


def test_help_renders_the_documentation_as_html(monkeypatch):
    transcript = evaluate(monkeypatch, 'help(len)')
    assert '<h3>Help on built-in function len' in transcript
    assert '<pre class=help>len(' in transcript
    assert evaluate(monkeypatch, 'help').endswith(
        '<span class="help">Type help(object) for help about object.</span>')


def test_exceptions_are_rendered_as_a_traceback(monkeypatch):
    transcript = evaluate(monkeypatch, '1/0')
    assert '<div class="traceback">' in transcript
    assert '<pre>1/0</pre>' in transcript  # the offending console line
    assert '<blockquote>ZeroDivisionError: division by zero</blockquote>' in transcript
