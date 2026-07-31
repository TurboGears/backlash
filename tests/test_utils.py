"""Behavioral tests for the HTML escaping helper.

``escape`` is the single sanitizer used by every rendering path, so it must
normalize non-string values and undecodable bytes before escaping them.
"""
from backlash.utils import escape


def test_escape_normalizes_values():
    assert escape(None) == ''
    assert escape(42) == '42'
    assert escape(b'pi\xc3\xb9 <b>') == 'pi\u00f9 &lt;b&gt;'
    assert escape('say "hi"', quote=True) == 'say &quot;hi&quot;'
