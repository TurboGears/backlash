"""Kept for backward compatibility only: the WSGI debugger historically
lived here as ``backlash.debug.DebuggedApplication``.

New code should use :class:`backlash.wsgi.WsgiDebuggedApplication` or
:class:`backlash.asgi.AsgiDebuggedApplication`.
"""
from backlash.wsgi import WsgiDebuggedApplication as DebuggedApplication

__all__ = ['DebuggedApplication']
