"""Behavioral tests for the HTML object representations of the debugger.

Pins the markup ``debug_repr`` produces for the types the debugger renders
most: strings, bytes, numbers, regexes, containers and broken objects.
"""
import re

from backlash.repr import debug_repr


def test_text_and_bytes_are_rendered_as_string_spans():
    assert debug_repr('hi') == '<span class="string">\'hi\'</span>'
    assert debug_repr(b'hi') == '<span class="string">b\'hi\'</span>'
    # binary payloads are decoded as utf-8 before being shown
    assert debug_repr(b'pi\xc3\xb9') == '<span class="string">b\'pi\u00f9\'</span>'


def test_html_in_values_is_escaped():
    assert debug_repr('<script>') == '<span class="string">\'&lt;script&gt;\'</span>'


def test_long_strings_are_truncated_into_an_extended_section():
    rendered = debug_repr('x' * 80)
    assert rendered.startswith('<span class="string">\'' + 'x' * 70)
    assert rendered.endswith('<span class="extended">' + 'x' * 10 + '\'</span></span>')


def test_regex_repr():
    assert debug_repr(re.compile('ab+')) == \
        're.compile(<span class="string regex">r\'ab+\'</span>)'


def test_containers_render_their_items():
    assert debug_repr([1, 'a']) == ('[<span class="number">1</span>, '
                                    '<span class="string">\'a\'</span>]')
    assert debug_repr({'a': 1}) == (
        '{<span class="pair"><span class="key"><span class="string">\'a\'</span>'
        '</span>: <span class="value"><span class="number">1</span></span>'
        '</span>}')


def test_subclasses_are_named_and_recursion_is_broken():
    class Recursive(list):
        pass

    recursive = Recursive()
    recursive.append(recursive)
    named = '<span class="module">%s.</span>Recursive' % __name__
    assert debug_repr(recursive) == '%s([%s([...])])' % (named, named)


def test_broken_repr_does_not_propagate():
    class Broken(object):
        def __repr__(self):
            raise RuntimeError('nope')

    assert debug_repr(Broken()) == ('<span class="brokenrepr">&lt;broken repr '
                                    '(RuntimeError: nope)&gt;</span>')
